import io

import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine.errors import EngineError
from badshop.engine.sheets import SliceSheetParams, grid_cells, slice_sheet
from badshop.session import project
from badshop.session.models import Source
from badshop.session.session import Session
from badshop.tools.registry import get, image_fields


def patterned(size=(17, 13)):
    image = Image.new("RGBA", size)
    image.putdata([(x * 11 % 256, y * 17 % 256, (x + y) * 7 % 256, 255)
                   for y in range(size[1]) for x in range(size[0])])
    return image


def encoded(image):
    data = io.BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


def test_sparse_indices_are_sorted_and_exact_with_remainders_margins_and_gaps():
    image = patterned()
    p = SliceSheetParams(image="sheet", rows=2, columns=3, margins=(1, 2, 2, 1), gap=(2, 1), cells=[5, 0, 3])
    assert p.cells == [0, 3, 5]
    geometry = grid_cells(p, image.size)
    assert [cell["box"] for cell in geometry] == [
        [1, 2, 5, 7], [7, 2, 10, 7], [12, 2, 15, 7],
        [1, 8, 5, 12], [7, 8, 10, 12], [12, 8, 15, 12],
    ]
    result = slice_sheet(p, image)
    assert [cell["index"] for cell in result.data["cells"]] == [0, 3, 5]
    assert [output.key for output in result.outputs] == ["cell_0", "cell_3", "cell_5"]
    for output, cell in zip(result.outputs, result.data["cells"], strict=True):
        assert output.image.tobytes() == image.crop(cell["box"]).tobytes()
        assert output.image.size == (cell["width"], cell["height"])
    assert [o.encode() for o in result.outputs] == [o.encode() for o in slice_sheet(p, image).outputs]


def test_alpha_padding_and_fully_transparent_tiles_are_preserved():
    image = Image.new("RGBA", (12, 4))
    image.putpixel((1, 2), (255, 40, 70, 255))
    image.putpixel((7, 1), (11, 77, 155, 127))
    outputs = slice_sheet(SliceSheetParams(image="sheet", columns=3), image).outputs
    assert [output.image.size for output in outputs] == [(4, 4)] * 3
    assert outputs[0].image.getpixel((1, 2)) == (255, 40, 70, 255)
    assert outputs[1].image.getpixel((3, 1)) == (11, 77, 155, 127)
    assert outputs[2].image.getbbox() is None
    assert len(outputs[2].image.tobytes()) == 64


@pytest.mark.parametrize("params", [
    {"rows": 0}, {"columns": 17}, {"rows": 2.5}, {"rows": True},
    {"margins": [-1, 0, 0, 0]}, {"margins": [0, 0, 0]}, {"gap": [1, -1]},
    {"gap": [0.5, 1]}, {"gap": [0, 100001]},
    {"cells": []}, {"cells": [0, 0]}, {"cells": [-1]}, {"cells": [1]}, {"cells": [False]},
    {"rows": 9, "columns": 8}, {"rows": 16, "columns": 16, "cells": list(range(65))},
])
def test_invalid_parameters_are_rejected(params):
    with pytest.raises(ValidationError):
        SliceSheetParams(image="sheet", **params)


@pytest.mark.parametrize("options", [
    {"margins": [10, 0, 0, 0]}, {"margins": [3, 4, 7, 4]},
    {"columns": 2, "gap": [9, 0]}, {"rows": 2, "gap": [0, 9]},
    {"columns": 11}, {"rows": 11},
])
def test_geometry_must_fit_inside_image(options):
    with pytest.raises(EngineError, match="at least one pixel"):
        slice_sheet(SliceSheetParams(image="sheet", **options), Image.new("RGB", (10, 10)))


def test_grid_and_output_limits_allow_last_cell_and_sixty_four_outputs():
    image = patterned((16, 16))
    last = slice_sheet(SliceSheetParams(image="sheet", rows=16, columns=16, cells=[255]), image)
    assert last.data["cells"] == [{"index": 255, "row": 15, "column": 15,
                                   "box": [15, 15, 16, 16], "width": 1, "height": 1}]
    assert last.outputs[0].image.getpixel((0, 0)) == image.getpixel((15, 15))
    assert len(slice_sheet(SliceSheetParams(image="sheet", rows=8, columns=8), image).outputs) == 64


def test_registered_tool_preserves_provenance_replay_and_saved_project(tmp_path):
    assert image_fields(get("slice_sheet").params) == {"image": False}
    source = Source(kind="local-collection", title="Sprite scan", creator="Artist", license="CC0")
    session = Session.new()
    image = session.import_image(encoded(patterned()), "sprite-sheet", source)
    step = session.run_tool("slice_sheet", {"image": image.id, "rows": 2, "columns": 3,
                                           "margins": [1, 2, 2, 1], "gap": [2, 1], "cells": [5, 0]}, "user")
    assert step.status == "done"
    assert step.params["cells"] == [0, 5]
    assert step.data["source_image"] == image.id
    assert "cell_0_r0_c0" in session.artifacts.meta[step.outputs[0]].label
    for output in step.outputs:
        assert session.artifacts.meta[output].produced_by == step.id
    downstream = session.run_tool("filter", {"image": step.outputs[1], "names": ["invert"]}, "user")
    originals = [session.artifacts.data(id) for id in step.outputs]
    path = tmp_path / "sheet.badshop"
    project.save(session, path)
    restored = project.open_project(path)
    assert restored.artifacts.meta[image.id].source == source
    saved_step = restored.step(step.id)
    assert saved_step.data == step.data
    assert saved_step.params == step.params
    assert [restored.artifacts.data(id) for id in saved_step.outputs] == originals
    replay = restored.replay_from(saved_step.id, use_cache=False)
    assert [s.status for s in replay] == ["done", "done"]
    assert replay[0].outputs == step.outputs
    assert replay[1].outputs == downstream.outputs
    assert [restored.artifacts.data(id) for id in replay[0].outputs] == originals


def test_invalid_grid_creates_no_partial_output_artifacts():
    session = Session.new()
    image = session.import_image(encoded(patterned()), "sheet")
    before = session.artifacts.ids()
    step = session.run_tool("slice_sheet", {"image": image.id, "columns": 3, "gap": [100, 0]}, "user")
    assert step.status == "error"
    assert step.outputs == []
    assert session.artifacts.ids() == before


def test_coordinates_follow_imported_working_copy():
    session = Session.new()
    image = session.import_image(encoded(Image.new("RGB", (1200, 24), "red")), "wide-sheet")
    assert image.width == 1000
    step = session.run_tool("slice_sheet", {"image": image.id, "columns": 2, "cells": [1]}, "user")
    assert step.status == "done"
    assert step.data["cells"][0]["box"] == [500, 0, 1000, image.height]
    assert session.artifacts.meta[image.original_id].width == 1200


def test_non_png_color_mode_uses_existing_rgb_conversion():
    from badshop.engine.common import to_rgb

    image = Image.new("CMYK", (6, 4), (25, 120, 3, 0))
    output = slice_sheet(SliceSheetParams(image="sheet", columns=2, cells=[1]), image).outputs[0]
    assert output.image.mode == "RGB"
    with Image.open(io.BytesIO(output.encode())) as restored:
        assert restored.tobytes() == to_rgb(image).crop((3, 0, 6, 4)).tobytes()
