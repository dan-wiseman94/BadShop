"""Where finished images go, shared by the CLI and sessions: the output folder and never-overwrite names."""

import os
from pathlib import Path

from badshop.engine.errors import EngineError


def default_output_dir() -> Path:
    """The user's output folder: $BADSHOP_OUT, else ~/Pictures/badshop (the CLI's rule since Plan 1)."""
    return Path(os.environ.get("BADSHOP_OUT") or Path.home() / "Pictures" / "badshop")


def final_path(final_dir: Path, stem: str, ext: str) -> Path:
    """Finished files never overwrite older ones: stem.ext, stem_2.ext, stem_3.ext...

    The stem must be a plain file name, so the file lands in final_dir itself. Params already refuse
    other names; this catches any caller that skipped them (a stem with a folder, a drive, or `..`)."""
    if stem in ("", ".", "..") or Path(stem).name != stem:  # this OS's separators and drives
        raise EngineError(f"bad file name {stem!r}: it must not contain folders",
                          hint="give a plain file name, e.g. lincoln_lasers")
    final_dir.mkdir(parents=True, exist_ok=True)
    p, i = final_dir / f"{stem}{ext}", 2
    while p.exists():
        p, i = final_dir / f"{stem}_{i}{ext}", i + 1
    return p
