"""Registry entry points: shared by desktop, CLI and MCP."""

from badshop.engine import retro
from badshop.engine import collections
from badshop.tools.registry import ToolSpec, register


def _add(name, params, run, category, summary):
    register(
        ToolSpec(
            name,
            params,
            run,
            summary,
            summary
            + ". Deterministic pixel operations; all scaling uses nearest neighbor. Parameters are saved in the editable timeline.",
            category,
        )
    )


_add(
    "retro_layout",
    retro.RetroParams,
    lambda p, s: retro.render(p, [s.load(r) for r in p.images]),
    "compose",
    "Compose an era-specific layout; inspect retro.list for the 28 supported styles",
)
_add(
    "canvas",
    retro.CanvasParams,
    lambda p, s: retro.canvas(p, s.load(p.image) if p.image else None),
    "compose",
    "Create a colored canvas or tile an existing image",
)
_add(
    "palette",
    retro.PaletteParams,
    lambda p, s: retro.palette(p, s.load(p.image)),
    "effects",
    "Map to a fixed mono, CGA, EGA, Game Boy, web or custom palette with optional dithering",
)
_add(
    "bitmap_text",
    retro.BitmapTextParams,
    lambda p, s: retro.bitmap_text(p, s.load(p.image)),
    "text",
    "Place bundled 6x11 Latin-1 bitmap text; exact mode refuses overflowing captions",
)
_add(
    "pattern",
    retro.PatternParams,
    lambda p, s: retro.pattern(p, s.load(p.image) if p.image else None),
    "compose",
    "Create seeded stars, checks, grid, scanlines or confetti",
)
_add(
    "animate_sticker",
    retro.AnimateStickerParams,
    lambda p, s: retro.animate_sticker(p, s.load(p.image), s.load(p.sticker)),
    "finish",
    "Compose a static or animated sticker with bounded frames and explicit frame delay",
)
_add(
    "export_profile",
    retro.ExportProfileParams,
    lambda p, s: retro.export_profile(p, s.load(p.image)),
    "finish",
    "Prepare exact-size buttons, blinkies, avatars, signatures or wallpaper; optional maximum bytes fails explicitly if unattainable",
)
register(
    ToolSpec(
        "collection_items",
        collections.CollectionParams,
        lambda p, s: collections.browse(p),
        "Browse a selected IIIF manifest, Archive item or Lospec palette",
        "Returns bounded candidates with provenance. Acquire only the selected image; for Lospec apply palette with returned colors. No bulk crawling.",
        "sources",
        mutates=False,
        network=True,
        read_only=False,
    )
)
