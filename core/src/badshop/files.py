"""Where finished images go, shared by the CLI and sessions: the output folder and never-overwrite names."""

import os
from pathlib import Path

from platformdirs import user_pictures_path

from badshop.engine.errors import EngineError


def expand_user_path(value: str) -> Path:
    path = Path(value)
    if os.name == "nt" and path.parts and path.parts[0].startswith("~") and path.parts[0] != "~":
        # Windows expanduser guesses a sibling profile directory, even for a nonexistent user.
        if not Path(path.parts[0]).expanduser().is_dir():
            raise RuntimeError("that home folder doesn't exist")
    return path.expanduser()


def default_output_dir() -> Path:
    """Use the configured export location, respecting the Windows Pictures folder if redirected."""
    override = os.environ.get("BADSHOP_OUT")
    if override:
        return Path(override)
    if os.name == "nt":
        try:
            return user_pictures_path() / "badshop"
        except (OSError, ValueError):
            pass  # Windows may not have initialized Pictures for this account yet.
    return Path.home() / "Pictures" / "badshop"


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
