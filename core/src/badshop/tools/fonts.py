"""Font choices safe for model calls; the user may still choose a font file by path."""

from badshop.engine import assets
from badshop.engine.text import SYSTEM_FONT_DIRS


def font_names() -> list[str]:
    names = set()
    for folder in [*SYSTEM_FONT_DIRS, assets.data_dir() / "fonts"]:
        try:
            for path in folder.rglob("*"):
                if path.suffix.lower() in (".ttf", ".otf", ".ttc") and path.is_file():
                    names.add(path.name)
        except OSError:
            continue
    return sorted(names)
