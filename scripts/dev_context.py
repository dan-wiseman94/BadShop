"""Small shared helpers for task provenance and isolated verification."""
from __future__ import annotations
import hashlib
import os
from contextlib import contextmanager
import json
import socket
import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, encoding='utf-8').strip()


def changed_paths(root: Path, base: str = 'HEAD') -> list[str]:
    paths = subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '-z', base]).split(b'\0')
    paths += subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z']).split(b'\0')
    return sorted({p.decode('utf-8') for p in paths if p})


def file_hash(path: Path) -> str | None:
    if path.is_symlink():
        return hashlib.sha256(str(path.readlink()).encode()).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def snapshot(root: Path) -> dict:
    changes = {p: file_hash(root / p) for p in changed_paths(root)}
    head = git(root, 'rev-parse', 'HEAD')
    fingerprint = hashlib.sha256(json.dumps([head, changes], sort_keys=True).encode()).hexdigest()
    return {'revision': head, 'changes': changes, 'fingerprint': fingerprint}


def private_ports() -> tuple[int, int]:
    # Hold both while selecting them. Strict bind at launch handles the small
    # release-to-launch race by failing, never by attaching to another server.
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        return first.getsockname()[1], second.getsockname()[1]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


@contextmanager
def checkout_lock(path: Path):
    """Do not let two runs rebuild the same frontend or native binary concurrently."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as lock:
        try:
            if os.name == 'nt':
                import msvcrt
                if path.stat().st_size == 0:
                    lock.write('0')
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another verification run owns this checkout; wait for it or use another worktree.') from exc
        yield
