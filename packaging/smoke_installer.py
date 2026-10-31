"""Install/extract a release artifact and exercise its actual desktop resource layout.

Linux: .deb payload extraction (no root), then the native smoke on an isolated X server.
Windows: per-user NSIS silent installation to a temporary directory, then normal launch.
macOS: attach the DMG, copy its .app out of the read-only volume, then normal launch.
The caller supplies a graphical session; missing display/keychain access is a failure.
"""
import argparse
import contextlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build_flatpak import extract_deb
from smoke_desktop import smoke

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--screenshot', type=Path, required=True)
    args = parser.parse_args()
    kind = {'linux': 'deb/*.deb', 'win32': 'nsis/*.exe', 'darwin': 'dmg/*.dmg'}[sys.platform]
    artifacts = [args.artifact] if args.artifact else list((ROOT / 'app/src-tauri/target/release/bundle').glob(kind))
    assert len(artifacts) == 1, f'Expected exactly one installer, found {artifacts}'
    artifact = artifacts[0].resolve()
    print(f'Installing desktop smoke artifact: {artifact}', flush=True)
    with tempfile.TemporaryDirectory(prefix='badshop-installed-') as temporary:
        root = Path(temporary)
        uninstaller = None
        if sys.platform == 'linux':
            extract_deb(artifact, root)
            executable = root / 'usr/bin/badshop-desktop'
        elif sys.platform == 'win32':
            target = root / 'installed'
            subprocess.run([str(artifact), '/S', '/D=' + str(target)], check=True, timeout=180)
            executable = target / 'badshop-desktop.exe'
            uninstallers = list(target.glob('*uninstall*.exe'))
            uninstaller = uninstallers[0] if uninstallers else None
        else:
            mount = root / 'volume'
            mount.mkdir()
            subprocess.run(['hdiutil', 'attach', str(artifact), '-readonly', '-nobrowse',
                            '-mountpoint', str(mount)], check=True, timeout=60)
            try:
                applications = list(mount.glob('*.app'))
                assert len(applications) == 1, f'Expected one application in {artifact}'
                app = root / applications[0].name
                shutil.copytree(applications[0], app, symlinks=True)
            finally:
                subprocess.run(['hdiutil', 'detach', str(mount)], check=True, timeout=30)
            info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
            executable = app / 'Contents/MacOS' / info['CFBundleExecutable']
        assert executable.is_file(), f'Installed executable missing: {executable}'
        try:
            smoke([str(executable)], args.screenshot)
        finally:
            if uninstaller:
                # NSIS's _?= form runs in place rather than starting a detached temp copy.
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    subprocess.run([str(uninstaller), '/S', '_?=' + str(uninstaller.parent)],
                                   check=True, timeout=60, env=os.environ)


if __name__ == '__main__':
    main()
