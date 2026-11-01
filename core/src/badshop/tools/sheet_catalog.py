"""Sprite-sheet extraction is available to the UI, CLI, and agent through normal tool steps."""

from badshop.engine.sheets import SliceSheetParams, slice_sheet
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="slice_sheet", params=SliceSheetParams, category="edit",
    run=lambda p, store: slice_sheet(p, store.load(p.image)),
    summary="extract exact sprite-sheet cells as separate images",
    description="Split an imported working image into rows and columns (each 1–16). Margins are left, top, "
                "right, bottom; gap is horizontal, vertical. Cells are zero-based row-major indices: "
                "row * columns + column. Omit cells for all, or select at most 64 unique indices; output order "
                "is sorted. After margins and gaps, integer division assigns one extra pixel to each of the "
                "first remainder rows/columns. Boxes use top-left coordinates with right/bottom exclusive. "
                "No scaling, alpha trimming, blending, or background removal; even transparent cells retain "
                "their exact size. Output cells and coordinates are recorded in structured data in output order.",
))
