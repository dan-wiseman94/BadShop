"""Atomic replacement of configuration and non-overwriting publication of exported bytes."""

import os
import tempfile
from pathlib import Path


def sync_directory(path: Path) -> None:
    """Persist published directory entries on POSIX; Windows uses file flushes."""
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_new_bytes(path: Path, data: bytes) -> None:
    """Publish complete bytes without replacing any existing destination.

    Windows rename refuses existing destinations. On POSIX, link provides the
    same atomic no-replace guarantee; unsupported filesystems fail safely.
    The sibling staging file is removed even when writing or publication fails.
    """
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".badshop-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if os.name == "nt":
            os.rename(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_text(path: Path, text: str) -> None:
    """Replace a UTF-8 file only after its complete contents have been written and closed.

    Create private temporary files beside the destination so replacement stays on one filesystem.
    Clean them up on every exit; leave error translation to the caller that knows the document.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
