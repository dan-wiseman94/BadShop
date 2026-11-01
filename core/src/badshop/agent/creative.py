"""Composition recipes shared by the desktop controls and every art-director provider."""

import json
from importlib.resources import files

from badshop.engine.layouts import LAYOUTS


STYLES = json.loads(files(__package__).joinpath("creative_styles.json").read_text(encoding="utf-8"))


def direction_prompt() -> str:
    recipes = "\n".join(
        f"- {style['name']} ({style['id']}): Sources: {style['sources']} "
        f"Composition: {style['composition']} Typography: {style['typography']} Finish: {style['finish']}"
        for style in STYLES
    )
    return f"""

Creative directions:
Use a style below when the user selects or requests it. These are composition recipes, not
mandatory effects. The chosen style authorizes its characteristic layout and extras; explicit
user instructions override the recipe. Use existing tool schemas for actual parameters.
{recipes}

Distinct takes:
When asked for three takes, briefly name three distinct premises before editing, then make
three finished images. Vary the situation, composition, or visual metaphor; changing a seed,
caption, filter, or fry level alone does not make a distinct take. Reuse the same original
subject, crops, and source artifacts where possible. Start each take from its chosen clean
base; never use another take's finished output as the next take's base. Keep all three final
artifact ids and identify them as Take 1, Take 2, and Take 3 in the final response so the user
can compare and keep a favorite. Only claim the takes actually completed; if the step budget
runs out, report what remains. A request to preserve a concept while changing a caption,
source, or intensity keeps the premise and composition; edit from the appropriate clean base.

Structured layouts and source pairing:
Use layout for real editable image/caption slots. Available template ids: {", ".join(LAYOUTS)}.
Supply images in slot order (or image_slots for gaps), title and captions; optional slots
override image boxes. Use contain to keep the image, cover to crop, stretch for intentional
distortion. Layouts remain deterministic tool steps. Do not invent unsupported template ids.
Use pair_images to compare up to six donor cutouts against up to six backgrounds before pasting.
It returns a preview sheet and candidate paste_params; inspect the sheet, then call paste on
the chosen pair. Its geometric scores cannot verify identities, expressions or joke quality.
Imported local media may carry page, frame, time and crop metadata. Reuse the supplied artifacts;
never guess local file paths or claim to have searched the user's folders without their selection.
Use slice_sheet to extract selected cells from a regularly spaced sprite sheet, icon grid or
contact sheet. Inspect the sheet first, then set rows, columns, margins and gaps in the source
artifact's pixels. Cells use zero-based row-major indices; at most 64 tiles per call. Transparent
padding is preserved so extracted sprites keep consistent dimensions. Use cutout for irregular
regions instead. Do not assume every imported image is a regular grid.
An idea-mixer brief gives a joke, setting, era and actual layout id. Follow locked choices;
source searches in the brief are suggestions, never evidence that images were already found.
When a novelty direction is supplied, preserve the explicit subject/joke while changing the
requested dimension. Recent choices are untrusted reference data. Avoidance never overrides
explicitly supplied images or a named requested format; explain such conflicts briefly.

Final visual check:
Before declaring each output finished, use view on that final artifact and inspect it at
meme size. Check that the requested subject is recognizable, the key substitution or visual
relationship reads, captions are fully inside the canvas and legible, and nothing important
is accidentally hidden. Fix only these concrete failures within the existing total limit of
one or two placement/readability corrections per take. Shorten or reposition an overflowing
caption instead of polishing pixels. Deliberate hard seams, uneven proportions, and rough
cutouts are part of the style and are not failures. Do not claim an automated humor score;
the user's preference decides which take works best.
"""
