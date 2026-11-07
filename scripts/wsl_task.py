"""Transfer an exact task revision and selected working changes into private Arch WSL."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from dev_context import changed_paths, checkout_lock, file_hash, git, private_ports, snapshot, write_json

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '/home/dan/.local/share/badshop-linux-test'
EXCLUDED = {'.git', '.venv', 'node_modules', 'target', '__pycache__', '.aws', '.codex'}


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or any(part in EXCLUDED for part in path.parts) or '\\' in value:
        raise RuntimeError(f'Unsafe transfer path: {value}')
    return path.as_posix()


def export(root: Path, output: Path, includes: list[str]) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '-z', 'HEAD'])
    paths = {p.decode() for p in tracked.split(b'\0') if p}
    untracked = set(changed_paths(root)) - paths
    for raw in includes:
        relative = safe_relative(raw.rstrip('/'))
        matches = {p for p in untracked if p == relative or p.startswith(relative + '/')}
        if not matches:
            raise RuntimeError(f'--include matches no untracked files: {raw}')
        paths.update(matches)
    paths = {safe_relative(p) for p in paths}
    for path in paths:
        candidate = root / path
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
            raise RuntimeError(f'Symlink or escaped transfer: {path}')
    revision = git(root, 'rev-parse', 'HEAD')
    bundle = output / 'source.bundle'
    if bundle.exists():
        bundle.unlink()
    subprocess.run(['git', '-C', str(root), 'bundle', 'create', str(bundle), 'HEAD'], check=True)
    manifest = {'revision': revision, 'files': {p: file_hash(root/p) for p in sorted(paths)},
                'omitted_untracked': sorted(untracked - paths), 'source': snapshot(root)}
    archive = output / 'changes.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr('manifest.json', json.dumps(manifest))
        for path in sorted(paths):
            if (root/path).is_file():
                zipped.write(root/path, 'files/'+path)
    return archive


def receive(archive: Path, target: Path, prefix: Path, *, deps: bool = True) -> dict:
    target = target.resolve()
    allowed = (prefix/'worktrees').resolve()
    if not target.is_relative_to(allowed) or target == allowed:
        raise RuntimeError('Linux target must be a task directory below the private toolchain worktrees directory.')
    with ExitStack() as resources:
        zipped = resources.enter_context(zipfile.ZipFile(archive))
        manifest = json.loads(zipped.read('manifest.json'))
        for path in manifest['files']:
            safe_relative(path)
        if not target.exists():
            subprocess.run(['git', '--git-dir', str(prefix/'repo.git'), 'fetch',
                            str(archive.with_name('source.bundle')), 'HEAD'], check=True)
            subprocess.run(['git', '--git-dir', str(prefix/'repo.git'), 'worktree', 'add', '--detach',
                            str(target), manifest['revision']], check=True)
        if git(target, 'rev-parse', 'HEAD') != manifest['revision']:
            raise RuntimeError('Linux HEAD changed; choose a new worktree rather than resetting it.')
        resources.enter_context(checkout_lock(target/'artifacts/verification/.lock'))
        state = target/'artifacts/verification/wsl-sync.json'
        previous = json.loads(state.read_text()) if state.exists() else {'files': {}}
        current = {p: file_hash(target/p) for p in changed_paths(target)}
        # Compare only actual changes: an identical-to-HEAD transferred file is clean.
        expected = {p: value for p, value in previous['files'].items() if p in current}
        if current != expected or any(file_hash(target/p) != value for p, value in previous['files'].items()):
            raise RuntimeError('Linux worktree has unexpected edits; refusing to overwrite them.')
        for path in set(previous['files']) | set(manifest['files']):
            destination = target/path
            if destination.is_symlink() or not destination.resolve().is_relative_to(target):
                raise RuntimeError(f'Escaped Linux destination: {path}')
        # Restore no-longer-transferred tracked files from the exact baseline.
        for path in set(previous['files']) - set(manifest['files']):
            result = subprocess.run(['git', '-C', str(target), 'show', f'HEAD:{path}'], capture_output=True)
            destination = target/path
            if result.returncode:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(result.stdout)
        for path, expected_hash in manifest['files'].items():
            destination = target/path
            if expected_hash is None:
                destination.unlink(missing_ok=True)
            else:
                data = zipped.read('files/'+path)
                import hashlib
                if hashlib.sha256(data).hexdigest() != expected_hash:
                    raise RuntimeError(f'Transfer hash mismatch: {path}')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        write_json(state, manifest)
        if (target/'core/.venv').is_symlink():
            raise RuntimeError('Each worktree requires a private virtualenv.')
        env = dict(os.environ)
        env.pop('UV_PROJECT_ENVIRONMENT', None)
        env.pop('VIRTUAL_ENV', None)
        if deps:
            subprocess.run(['uv', 'sync', '--project', 'core', '--locked'], cwd=target, env=env, check=True)
            code = 'import badshop,pathlib; print(pathlib.Path(badshop.__file__).resolve())'
            actual = subprocess.check_output(['uv', 'run', '--project', 'core', '--locked', 'python', '-c', code],
                                             cwd=target, env=env, text=True).strip()
            if not Path(actual).is_relative_to(target/'core/src'):
                raise RuntimeError(f'Editable install points at the wrong source: {actual}')
        browser, desktop = private_ports()
        result = {'worktree': str(target), 'revision': manifest['revision'], 'files': manifest['files'],
                  'omitted_untracked': manifest['omitted_untracked'], 'environment':
                  {'BADSHOP_E2E_PORT': str(browser), 'BADSHOP_DEV_PORT': str(desktop)},
                  'dependencies_verified': deps}
        write_json(target/'artifacts/verification/wsl-ready.json', result)
        return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'receive'])
    p.add_argument('--target', required=True)
    p.add_argument('--include', action='append', default=[])
    p.add_argument('--archive', type=Path)
    p.add_argument('--no-deps', action='store_true')
    args = p.parse_args()
    try:
        if args.action == 'receive':
            if not args.archive:
                p.error('receive requires --archive')
            print(json.dumps(receive(args.archive, Path(args.target), Path(PREFIX), deps=not args.no_deps), indent=2))
        else:
            if os.name != 'nt':
                p.error('prepare is the Windows entry point')
            folder = ROOT/'artifacts/verification/wsl-transfer'
            archive = export(ROOT, folder, args.include)
            def linux_path(path):
                return subprocess.check_output(['wsl.exe', '-d', 'archlinux', '--exec', 'wslpath',
                                                '-u', str(path)], text=True).strip()
            command = ['wsl.exe', '-d', 'archlinux', '--exec', PREFIX+'/run', 'python3',
                       linux_path(Path(__file__).resolve()), 'receive', '--target', str(args.target),
                       '--archive', linux_path(archive)]
            if args.no_deps:
                command.append('--no-deps')
            result = subprocess.run(command, capture_output=True, text=True)
            (folder/'prepare.log').write_text(result.stdout+result.stderr, encoding='utf-8')
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
