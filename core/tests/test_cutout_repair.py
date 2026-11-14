import pytest
from PIL import Image

from badshop.engine.cutout import CutoutParams, cutout
from badshop.engine.errors import EngineError


def test_repair_restores_source_rgb_and_removes_overlap_in_original_coordinates():
    source = Image.new("RGBA", (12, 12), (17, 33, 99, 0))
    params = CutoutParams(image="x", box=(2, 2, 10, 10), no_ai=True,
        keep_regions=[[(2, 2), (9, 2), (9, 9), (2, 9)]],
        remove_regions=[[(4, 4), (6, 4), (6, 6), (4, 6)]])
    output = cutout(params, source).outputs[0]
    assert output.image.size == (8, 8)
    assert output.image.getpixel((0, 0)) == (17, 33, 99, 255)
    assert output.image.getpixel((3, 3)) == (17, 33, 99, 0)
    assert set(output.image.getchannel("A").getdata()) == {0, 255}
    assert output.encode() == cutout(params, source).outputs[0].encode()
    assert source.getpixel((2, 2))[3] == 0


def test_removing_entire_subject_returns_actionable_error():
    with pytest.raises(EngineError, match="nothing was kept"):
        cutout(CutoutParams(image="x", no_ai=True,
            remove_regions=[[(0, 0), (9, 0), (9, 9), (0, 9)]]),
            Image.new("RGB", (10, 10), "red"))
