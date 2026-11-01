"""Exact, deterministic grid crops of an already imported working image."""

from typing import Annotated, ClassVar

from PIL import Image
from pydantic import Field, model_validator

from badshop.engine.common import has_alpha, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import ImageRef, Params

Pixels = Annotated[int, Field(ge=0, le=100_000, strict=True)]
CellIndex = Annotated[int, Field(ge=0, le=255, strict=True)]


class SliceSheetParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="Imported sprite sheet; coordinates use this working image's pixels")
    rows: int = Field(1, ge=1, le=16, strict=True)
    columns: int = Field(1, ge=1, le=16, strict=True)
    margins: tuple[Pixels, Pixels, Pixels, Pixels] = Field(
        (0, 0, 0, 0), description="Pixels to exclude at left, top, right, bottom, in that order")
    gap: tuple[Pixels, Pixels] = Field((0, 0), description="Horizontal and vertical gaps between cells, in pixels")
    cells: list[CellIndex] | None = Field(
        None, min_length=1, max_length=64,
        description="Zero-based row-major indices; unique indices are sorted. Omit for all cells (at most 64)")

    @model_validator(mode="after")
    def valid_selection(self):
        count = self.rows * self.columns
        if self.cells is None:
            if count > 64:
                raise ValueError("select at most 64 cells explicitly for grids larger than 64 cells")
        else:
            if len(set(self.cells)) != len(self.cells):
                raise ValueError("cells must contain unique indices")
            if any(index >= count for index in self.cells):
                raise ValueError(f"cell indices must be between 0 and {count - 1}")
            self.cells = sorted(self.cells)
        return self


def grid_cells(p: SliceSheetParams, size: tuple[int, int]) -> list[dict]:
    """End-exclusive boxes; the first remainder rows/columns each receive one extra pixel."""
    width, height = size
    left, top, right, bottom = p.margins
    gap_x, gap_y = p.gap
    usable_w = width - left - right - gap_x * (p.columns - 1)
    usable_h = height - top - bottom - gap_y * (p.rows - 1)
    if usable_w < p.columns or usable_h < p.rows:
        raise EngineError("margins and gaps must leave at least one pixel per row and column",
                          hint=f"the selected image is {width} × {height} pixels; reduce margins, gaps, or grid size")
    cell_w, extra_w = divmod(usable_w, p.columns)
    cell_h, extra_h = divmod(usable_h, p.rows)
    cells = []
    for index in range(p.rows * p.columns):
        row, column = divmod(index, p.columns)
        x = left + column * (cell_w + gap_x) + min(column, extra_w)
        y = top + row * (cell_h + gap_y) + min(row, extra_h)
        w, h = cell_w + (column < extra_w), cell_h + (row < extra_h)
        cells.append({"index": index, "row": row, "column": column,
                      "box": [x, y, x + w, y + h], "width": w, "height": h})
    return cells


def slice_sheet(p: SliceSheetParams, image: Image.Image) -> EngineResult:
    geometry = grid_cells(p, image.size)  # Validate the entire grid before producing any outputs.
    if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16", "I;16B"):
        # PNG cannot represent CMYK/HSV/etc. Use the existing color-mode conversion helpers;
        # supported PNG modes retain their original samples and palette transparency.
        image = image.convert("RGBA") if has_alpha(image) else to_rgb(image)
    chosen = p.cells if p.cells is not None else range(len(geometry))
    cells = [geometry[index] for index in chosen]
    outputs = []
    for cell in cells:
        index, row, column = cell["index"], cell["row"], cell["column"]
        # The rectangle primitive used by cutout, without that tool's alpha trimming. Sprite tiles
        # require exact dimensions, including fully transparent cells and transparent edge padding.
        tile = image.crop(tuple(cell["box"]))
        outputs.append(Output(f"cell_{index}", tile, f"{{stem}}_cell_{index}_r{row}_c{column}.png",
                              caption=f"cell {index}, row {row}, column {column}; box {cell['box']}"))
    return EngineResult(outputs=outputs,
                        lines=[f"Extracted {len(cells)} cells from a {p.rows} × {p.columns} grid (zero-based indices)"],
                        data={"source_image": p.image, "rows": p.rows, "columns": p.columns,
                              "margins": list(p.margins), "gap": list(p.gap), "cells": cells})
