"""Content identity for replay, independent of the human release version."""

import hashlib
import sys
from functools import lru_cache
from pathlib import Path


def source_identity(root: Path) -> str:
    """Hash package source in stable order, including uncommitted development edits."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix().encode()
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def build_identity() -> str:
    if getattr(sys, "frozen", False):
        # The packaging spec computes this from the exact source being bundled.
        return (Path(__file__).parent / "build-identity.txt").read_text().strip()
    return source_identity(Path(__file__).parent)
