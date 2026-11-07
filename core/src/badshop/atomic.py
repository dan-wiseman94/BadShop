"""Atomic replacement of small configuration files, independent of their format."""

import os
import tempfile
from pathlib import Path


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
