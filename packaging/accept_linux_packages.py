"""Real package-manager upgrade, recovery, and removal on a disposable Linux runner."""
import asyncio
import hashlib
import json
import os
import subprocess
import shlex
from pathlib import Path

from smoke_desktop import smoke
from smoke_core import smoke as core_smoke


def run(*args):
    subprocess.run(list(map(str, args)), check=True, timeout=600)


def packages(candidate, root, output):
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    baseline = root / 'package-baseline'
    baseline.mkdir()
    run('gh', 'release', 'download', 'v0.4.3', '--dir', baseline, '--pattern', '*.deb', '--pattern', '*.flatpak')
    previous_deb, = baseline.glob('*.deb')
    next_deb, = candidate.glob('*.deb')
    package = subprocess.check_output(['dpkg-deb', '-f', str(next_deb), 'Package'], text=True).strip()
    version = json.loads((candidate / 'latest.json').read_text())['version']
    summary = {'status': 'failed', 'checks': []}
    try:
        run('sudo', 'apt-get', 'install', '-y', '--allow-downgrades', previous_deb)
        smoke(['/usr/bin/badshop-desktop'], output / 'deb-baseline.png', restart_core=True)
        saved = output / 'deb-baseline-native-recovered.badshop'
        before = hashlib.sha256(saved.read_bytes()).hexdigest()
        run('sudo', 'apt-get', 'install', '-y', next_deb)
        installed = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', package], text=True)
        assert installed == version
        smoke(['/usr/bin/badshop-desktop'], output / 'deb-upgraded.png', project_to_open=saved)
        assert hashlib.sha256(saved.read_bytes()).hexdigest() == before
        run('sudo', 'apt-get', 'remove', '-y', package)
        assert not Path('/usr/bin/badshop-desktop').exists()
        summary['checks'].append('deb package-manager upgrade, project pixels, unchanged saved bytes, uninstall')
        run('flatpak', 'remote-add', '--user', '--if-not-exists', 'flathub', 'https://flathub.org/repo/flathub.flatpakrepo')
        run('flatpak', 'install', '--user', '-y', 'flathub', 'org.gnome.Platform//49')
        run('flatpak', 'install', '--user', '-y', baseline / 'badshop.flatpak')
        command = ['flatpak', 'run', 'io.github.danwiseman94.badshop']
        smoke(command, output / 'flatpak-baseline.png', restart_core=True)
        saved = output / 'flatpak-baseline-native-recovered.badshop'
        before = hashlib.sha256(saved.read_bytes()).hexdigest()
        run('flatpak', 'install', '--user', '-y', candidate / 'badshop.flatpak')
        location = Path(subprocess.check_output(['flatpak', 'info', '--user', '--show-location',
                                                'io.github.danwiseman94.badshop'], text=True).strip())
        cores = [p for p in (location / 'files').rglob('badshop-core') if p.is_file()]
        assert len(cores) == 1
        sandbox_core = '/app/' + cores[0].relative_to(location / 'files').as_posix()
        wrapper = root / 'flatpak-core'
        wrapper.write_text('#!/bin/sh\nexec flatpak run --filesystem="$(dirname "$BADSHOP_OUT")" '
                           + '--command=' + shlex.quote(sandbox_core)
                           + ' io.github.danwiseman94.badshop "$@"\n')
        wrapper.chmod(0o755)
        # The wrapper PID is Flatpak's launcher, not the frozen core. Exercise
        # keychain and clean EOF here; crash the actual core through its native
        # supervisor below instead of killing the launcher and orphaning its pipes.
        asyncio.run(core_smoke(wrapper, keychain=True, metrics=output / 'flatpak-keychain.json'))
        summary['checks'].append('installed Flatpak core stored, retrieved and deleted synthetic keychain credential')
        installed = subprocess.check_output(['flatpak', 'info', '--user', 'io.github.danwiseman94.badshop'], text=True)
        (output / 'flatpak-installed.txt').write_text(installed)
        smoke(command, output / 'flatpak-candidate-recovery.png', restart_core=True)
        smoke(command, output / 'flatpak-upgraded.png', project_to_open=saved)
        assert hashlib.sha256(saved.read_bytes()).hexdigest() == before
        run('flatpak', 'uninstall', '--user', '-y', 'io.github.danwiseman94.badshop')
        result = subprocess.run(['flatpak', 'info', '--user', 'io.github.danwiseman94.badshop'],
                                capture_output=True, check=False)
        assert result.returncode != 0
        summary['checks'].append('Flatpak bundle upgrade, project pixels, unchanged saved bytes, uninstall')
        summary['status'] = 'passed'
    finally:
        (output / 'linux-packages.json').write_text(json.dumps(summary, indent=2))
