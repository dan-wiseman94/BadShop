# Sprite sheets and image grids

Open the sprite-sheet panel in the studio, choose an imported image, and set rows,
columns, margins, and gaps. The preview shows selectable cell indices. Click a cell
or focus it and press Space/Enter. **Extract selected and attach** creates the
chosen tiles and attaches them to chat. **Extract all and attach** uses every cell
when the grid has at most 64 cells. The resulting images can be used by any normal
composition tool, saved in the asset library, or exported in a pack.

The `slice_sheet` tool is also available to agents and the CLI. It uses the normal
tool timeline, approval policy, editable parameters, replay, and project saving.
There are no new dependencies or image-generation calls.

```json
{
  "image": "<imported artifact id>",
  "rows": 2,
  "columns": 3,
  "margins": [1, 2, 2, 1],
  "gap": [2, 1],
  "cells": [0, 3, 5]
}
```

Rows and columns are each 1–16, defaulting to 1 for the tool. The visual picker
starts at 2×2. Margins default to zero and are **left, top, right, bottom**; gaps
default to zero and are **horizontal, vertical**. These values are whole pixels of
the selected image. Imported working copies have a maximum dimension of 1000;
use the dimensions shown in the picker, not the full-resolution original's.

Cell indices start at zero in row-major order: `index = row * columns + column`.
Rows and columns in output metadata also start at zero. Unique unsorted indices
are sorted before execution; duplicate, negative, empty, or out-of-range selections
are rejected. Omit `cells` to select every cell. A call produces at most 64 tiles,
so larger grids require an explicit selection of at most 64 indices.

After subtracting margins and all gaps, each usable axis is divided by the number
of cells with integer division. The first remainder columns or rows get one extra
pixel. For a 17×13 image with the example settings, cell boxes are:

| Index | Row | Column | Box `[left, top, right, bottom]` | Size |
| --- | --- | --- | --- | --- |
| 0 | 0 | 0 | `[1, 2, 5, 7]` | 4×5 |
| 1 | 0 | 1 | `[7, 2, 10, 7]` | 3×5 |
| 2 | 0 | 2 | `[12, 2, 15, 7]` | 3×5 |
| 3 | 1 | 0 | `[1, 8, 5, 12]` | 4×4 |
| 4 | 1 | 1 | `[7, 8, 10, 12]` | 3×4 |
| 5 | 1 | 2 | `[12, 8, 15, 12]` | 3×4 |

Right and bottom coordinates are exclusive. All cells must have at least one
pixel in each dimension. Invalid geometry is rejected before any tile is created.
Pixels are copied directly: no resizing, blending, background removal, or alpha
trimming. Transparent padding and entirely transparent cells retain their exact
size. Existing source transparency is preserved.
Color modes PNG cannot represent, such as CMYK JPEGs, use the engine's existing
RGB conversion before cropping.

Outputs are PNGs named with their cell, row, and column, such as
`sheet_cell_5_r1_c2.png`. Structured step data records `source_image`, grid settings,
and each selected cell's `index`, `row`, `column`, `box`, `width`, and `height` in
output order. The input artifact and its original source metadata remain in the
project, linked through the step's image parameter. Identical tile bytes use the
existing content-addressed artifact store; repeated tiles may share an artifact
ID while their cell indices and bounds remain distinct in step data.

The rectangle operation follows [Pillow's crop coordinate convention](https://pillow.readthedocs.io/en/stable/handbook/concepts.html#coordinate-system).
