"""Owned temporary directories with conservative recovery after a killed core.

Only this version's marker-bearing directories are eligible. A live process,
unknown owner, unreadable marker or fresh directory prevents deletion.
"""

import json
import re
import shutil
import tempfile
import time
from pathlib import Path

import psutil

MARKER = '.badshop-owner-v1.json'
NAME = re.compile(r'badshop-(?:blobs|media)-[a-z0-9_]{8}')


def temporary(kind: str):
    if kind not in ('blobs', 'media'):
        raise ValueError('unknown scratch owner')
    directory = tempfile.TemporaryDirectory(prefix=f'badshop-{kind}-')
    try:
        process = psutil.Process()
        marker = {'version': 1, 'pid': process.pid, 'started': process.create_time(), 'created': time.time()}
        (Path(directory.name) / MARKER).write_text(json.dumps(marker), encoding='utf-8')
    except BaseException:
        directory.cleanup()
        raise
    return directory


def collect(root: Path | None = None, *, grace_seconds: float = 86400) -> None:
    root = (root or Path(tempfile.gettempdir())).resolve()
    now = time.time()
    try:
        paths = list(root.iterdir())
    except OSError:
        return
    for path in paths:
        try:
            if not NAME.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
                continue
            # Never follow a Windows junction or a computed path outside this root.
            if path.resolve().parent != root:
                continue
            marker_path = path / MARKER
            if marker_path.is_symlink() or marker_path.stat().st_size > 1024:
                continue
            marker = json.loads(marker_path.read_text(encoding='utf-8'))
            if (marker.get('version') != 1 or type(marker.get('pid')) is not int
                    or marker['pid'] <= 0 or not isinstance(marker.get('started'), (int, float))
                    or not isinstance(marker.get('created'), (int, float))
                    or now - marker['created'] < grace_seconds):
                continue
            try:
                if psutil.Process(marker['pid']).create_time() == marker['started']:
                    continue
            except psutil.NoSuchProcess:
                pass
            # A reused PID is not the owner. Access-denied/unknown status is caught
            # below and preserves the directory; it is not evidence of death.
            shutil.rmtree(path)
        except (OSError, ValueError, TypeError, psutil.Error):
            continue
