import typing

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.engine.filters import FILTERS, FilterName
from badshop.engine.garnish import WATERMARKS, WatermarkParams
from badshop.tools.runner import run_tool
from conftest import FIXTURES
from memstore import MemoryStore

CASES = [
    ["draw", "lincoln.png", "--circle", "300", "250", "80", "--arrow", "550", "550", "350", "350",
     "--line", "0", "0", "100", "100", "--rect", "10", "10", "200", "120", "--color", "lime", "--width", "4"],
    ["censor", "lincoln.png", "--box", "200", "200", "400", "260"],
    ["censor", "lincoln.png", "--box", "200", "200", "400", "260", "--box", "0", "0", "50", "50", "--style", "bar"],
    ["censor", "lincoln.png", "--box", "200", "200", "400", "260", "--style", "blur", "--block", "6"],
    ["eyes", "lincoln.png", "--at", "260", "240", "--at", "340", "238"],
    ["eyes", "lincoln.png", "--at", "260", "240", "--angle", "30", "--size", "9", "--color", "cyan"],
    ["filter", "lincoln.png", "posterize", "sepia"],
    ["filter", "lincoln.png", "emboss", "solarize", "invert"],
    ["warp", "lincoln.png", "--at", "260", "240", "40", "--at", "340", "238", "40", "--strength", "0.8"],
    ["warp", "lincoln.png", "--at", "300", "300", "90", "--strength", "-0.5"],
    ["warp", "lincoln.png", "--at", "300", "300", "90", "--strength", "1"],
]


@pytest.mark.parametrize("args", CASES, ids=lambda a: " ".join(a[:2] + a[-2:]))
def test_parity(pair, args):
    ref, new = pair.ref(*args).stdout, pair.new(*args).stdout
    assert new == ref
    pair.assert_same("badshop_work/result.png")


def test_draw_needs_a_shape():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (20, 20)), "x.png")
    with pytest.raises(EngineError, match="nothing to draw"):
        run_tool("draw", {"image": ref}, store)


def test_draw_negative_radius_is_a_clean_error():
    # the reference crashes in PIL here (x1 must be greater than or equal to x0)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (20, 20)), "x.png")
    with pytest.raises(EngineError, match="radius -5"):
        run_tool("draw", {"image": ref, "circle": [[10, 10, -5]]}, store)


def test_censor_needs_a_box():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (20, 20)), "x.png")
    with pytest.raises(EngineError, match="bad parameters"):
        run_tool("censor", {"image": ref, "box": []}, store)


def test_every_filter_matches_the_reference(reference):
    # The CLI parity CASES chain five filters; this runs all eleven, alone, against the reference's own.
    assert set(reference.FILTERS) == set(FILTERS) == set(typing.get_args(FilterName))
    with Image.open(FIXTURES / "lincoln.png") as src:
        im = src.convert("RGB")
    for name in FILTERS:
        assert FILTERS[name](im).tobytes() == reference.FILTERS[name](im).tobytes(), name


def test_watermark_names_match_the_watermarks(reference):
    (names,) = typing.get_args(WatermarkParams.model_fields["names"].annotation)  # list[Literal[...]]
    assert typing.get_args(names) == WATERMARKS == reference.WATERMARKS
