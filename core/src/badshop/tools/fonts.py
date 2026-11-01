"""Font choices safe for model calls; the user may still choose a font file by path."""

import json

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


def model_font_schema() -> dict:
    """Keep large desktop font libraries out of every model's context window.

    Small catalogues remain explicit. Larger ones accept any installed name, with a
    bounded hint; runner.validate still checks the complete discovered-name allowlist.
    """
    names = font_names()
    description = "A discovered font name; omit to use the style's default font."
    if len(names) <= 32:
        choices = [{"type": "string", "enum": names}] if names else []
    else:
        choices = [{"type": "string", "maxLength": 255, "pattern": r"^[^/\\:]+$"}]
        # Bound bytes as well as count: installed names can themselves be long.
        examples = []
        for name in names:
            if len(examples) >= 16 or len(json.dumps([*examples, name])) > 1024:
                break
            examples.append(name)
        description += (" Only installed file names are accepted, never paths. "
                        "Examples (not the complete list): " + json.dumps(examples))
    return {"anyOf": [*choices, {"type": "null"}], "default": None, "description": description}
