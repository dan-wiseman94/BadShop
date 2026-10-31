"""Bundle the already verified Linux .deb, preserving its native resource layout.

Requires flatpak-builder >= 1.3.4 and org.gnome.{Sdk,Platform}//49.
No host package installation.
"""
import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def require_builder() -> None:
    """SDK 49 needs a builder that composes metadata with appstreamcli."""
    version = subprocess.check_output(['flatpak-builder', '--version'], text=True)
    match = re.search(r'\b(\d+)\.(\d+)\.(\d+)\b', version)
    if not match or tuple(map(int, match.groups())) < (1, 3, 4):
        raise SystemExit('GNOME SDK 49 requires flatpak-builder >= 1.3.4 (appstreamcli compose)')


def extract_deb(deb: Path, staging: Path) -> None:
    """Extract the payload on Debian hosts and on hosts with standard archive tools."""
    if shutil.which('dpkg-deb'):
        subprocess.run(['dpkg-deb', '-x', str(deb), str(staging)], check=True)
        return
    if not shutil.which('ar') or not shutil.which('bsdtar'):
        raise SystemExit('Extracting a .deb requires dpkg-deb, or both ar and bsdtar')
    members = subprocess.check_output(['ar', 't', str(deb)], text=True).splitlines()
    payloads = [name for name in members if name == 'data.tar' or name.startswith('data.tar.')]
    if len(payloads) != 1:
        raise SystemExit('The .deb must contain exactly one data.tar payload')
    # Avoid holding the compressed onedir in memory; bsdtar detects its compression format.
    with tempfile.TemporaryFile() as payload:
        subprocess.run(['ar', 'p', str(deb), payloads[0]], stdout=payload, check=True)
        payload.seek(0)
        subprocess.run(['bsdtar', '-x', '-f', '-', '-C', str(staging)], stdin=payload, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('deb', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not args.prepare_only:
        require_builder()
    staging = ROOT / 'packaging/flatpak-input'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    extract_deb(args.deb.resolve(), staging)
    for name in ('io.github.danwiseman94.badshop.desktop', 'io.github.danwiseman94.badshop.metainfo.xml'):
        shutil.copy(ROOT / 'packaging' / name, staging / name)
    shutil.copy(ROOT / 'app/src-tauri/icons/512x512.png', staging / 'icon.png')
    if args.prepare_only:
        return
    subprocess.run(['flatpak-builder', '--force-clean', '--user', '--repo=flatpak-repo',
                    'flatpak-build', 'flatpak.json'], cwd=ROOT / 'packaging', check=True)
    subprocess.run(['flatpak', 'build-bundle', 'flatpak-repo', 'badshop.flatpak',
                    'io.github.danwiseman94.badshop'], cwd=ROOT / 'packaging', check=True)


if __name__ == '__main__':
    main()
