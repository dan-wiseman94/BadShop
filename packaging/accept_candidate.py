"""Inspect downloaded release bytes on disposable native Actions runners.

This does not generate an acceptance approval: it retains measured results for review.
It deliberately refuses the developer's workstation because it installs/uninstalls packages.
"""
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_gate import track
from smoke_desktop import smoke

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/verification/candidate-acceptance'


def run(*args, **kwargs):
    print('Running:', *map(str, args), flush=True)
    return subprocess.run(list(map(str, args)), check=True, timeout=600, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_legal(root, candidate, label):
    matches = list(root.rglob('legal/sbom.json'))
    assert len(matches) == 1, f'Expected one installed legal inventory: {matches}'
    legal = matches[0].parent
    sidecar = candidate / f'badshop-{label}.sbom.json'
    assert digest(matches[0]) == digest(sidecar), 'Installed SBOM differs from release sidecar'
    inventory = json.loads(sidecar.read_text())
    reviews = json.loads((candidate / f'badshop-{label}.licenses.json').read_text())['manual_license_review']
    required = {row['package'] for row in reviews}
    report = []
    for component in inventory['components']:
        properties = {row['name']: row['value'] for row in component['properties']}
        notices = json.loads(properties['badshop:license-notices'])
        for notice in notices:
            path = legal / notice['file']
            assert path.is_relative_to(legal) and digest(path) == notice['sha256'], path
        if component['purl'] not in required:
            continue
        texts = [(legal / row['file']).read_text(errors='replace') for row in notices]
        row = {'package': component['purl'], 'licenses': component['licenses'],
               'notices_verified': notices}
        if component['name'] == 'selectors':
            source = legal / properties['badshop:covered-source']
            assert (source / 'Cargo.toml').is_file() and (source / 'lib.rs').is_file()
            assert any('Mozilla Public License' in text for text in texts)
            row['covered_source_files'] = {p.relative_to(source).as_posix(): digest(p)
                                           for p in sorted(source.rglob('*')) if p.is_file()}
            row['source_included'] = True
        else:
            assert any('Permission is hereby granted' in text for text in texts), component['purl']
            assert any('Apple SDK' in text for text in texts), component['purl']
            row['mit_and_sdk_notices_included'] = True
        report.append(row)
    assert {row['package'] for row in report} == required
    (OUT / 'license-inspection.json').write_text(json.dumps(report, indent=2) + '\n')


def main():
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Use a disposable Actions runner'
    tag, label = os.environ['CANDIDATE_TAG'], os.environ['CANDIDATE_LABEL']
    track(tag)
    OUT.mkdir(parents=True, exist_ok=True)
    candidate = ROOT / 'candidate-download'
    candidate.mkdir()
    patterns = {
        'windows-x64': ['*x64-setup.exe*'],
        'macos-arm64': ['*aarch64.dmg', '*macos-arm64.app.tar.gz*'],
        'macos-x64': ['*x64.dmg', '*macos-x64.app.tar.gz*'],
        'linux-x64': ['*.AppImage*', '*.deb*', '*.flatpak'],
    }[label]
    patterns += ['SHA256SUMS', 'release-candidate.json', 'latest.json', f'badshop-{label}.*.json']
    run('gh', 'release', 'download', tag, '--dir', candidate,
        *[arg for pattern in patterns for arg in ('--pattern', pattern)])
    expected = dict(line.split('  ', 1)[::-1] for line in (candidate / 'SHA256SUMS').read_text().splitlines())
    measured = {}
    for path in candidate.iterdir():
        if path.name != 'SHA256SUMS':
            measured[path.name] = digest(path)
            assert measured[path.name] == expected[path.name], path
    summary = {'tag': tag, 'label': label, 'sha256sums': digest(candidate / 'SHA256SUMS'),
               'assets': measured, 'checks': {}, 'status': 'failed'}
    try:
        with tempfile.TemporaryDirectory(prefix='badshop-acceptance-') as folder:
            root = Path(folder).resolve()
            if sys.platform == 'win32':
                installer, = candidate.glob('*.exe')
                target = root / 'installed'
                run(installer, '/S', '/D=' + str(target))
                executable = target / 'badshop-desktop.exe'
                assert executable.is_file()
                inspect_legal(target, candidate, label)
                run('powershell', '-NoProfile', '-Command',
                    f"Get-AuthenticodeSignature -LiteralPath '{installer}' | Select-Object Status,StatusMessage | ConvertTo-Json",
                    stdout=(OUT / 'os-trust.json').open('w'))
                from smoke_windows_edit import smoke_editing
                smoke_editing(executable, OUT / 'native.png', ROOT / 'core/tests/fixtures/lincoln.png', root)
                summary['checks']['native_files'] = 'passed'
                uninstallers = list(target.glob('*uninstall*.exe'))
                assert len(uninstallers) == 1
                run(uninstallers[0], '/S', '_?=' + str(target))
                assert not executable.exists(), 'Uninstaller left the application installed'
                summary['checks']['install_uninstall'] = 'passed'
            elif sys.platform == 'darwin':
                installer, = candidate.glob('*.dmg')
                mount = root / 'mount'
                mount.mkdir()
                run('hdiutil', 'attach', installer, '-readonly', '-nobrowse', '-mountpoint', mount, input=b'Y\n')
                try:
                    source, = mount.glob('*.app')
                    target = root / source.name
                    shutil.copytree(source, target, symlinks=True)
                finally:
                    run('hdiutil', 'detach', mount)
                info = plistlib.loads((target / 'Contents/Info.plist').read_bytes())
                executable = target / 'Contents/MacOS' / info['CFBundleExecutable']
                inspect_legal(target, candidate, label)
                trust = subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=4', str(target)],
                                       capture_output=True, text=True, timeout=60)
                (OUT / 'os-trust.json').write_text(json.dumps({'exit_code': trust.returncode,
                    'stdout': trust.stdout, 'stderr': trust.stderr}, indent=2))
                smoke([str(executable)], OUT / 'native.png')
                shutil.rmtree(target)
                assert not target.exists()
                summary['checks']['install_uninstall'] = 'passed'
            else:
                installer, = candidate.glob('*.deb')
                run('sudo', 'apt-get', 'install', '-y', str(installer))
                executable = Path('/usr/bin/badshop-desktop')
                assert executable.is_file()
                inspect_legal(Path('/usr/lib'), candidate, label)
                smoke([str(executable)], OUT / 'deb.png', restart_core=True)
                summary['checks']['deb_native_files'] = 'passed'
                summary['checks']['deb_project_recovery'] = 'passed'
                package = subprocess.check_output(['dpkg-deb', '-f', str(installer), 'Package'], text=True).strip()
                run('sudo', 'apt-get', 'remove', '-y', package)
                assert not executable.exists()
                summary['checks']['deb_install_uninstall'] = 'passed'
                appimage, = candidate.glob('*.AppImage')
                appimage.chmod(0o755)
                smoke([str(appimage)], OUT / 'appimage.png', restart_core=True)
                summary['checks']['appimage_runtime'] = 'passed'
            summary['status'] = 'passed'
    finally:
        (OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
