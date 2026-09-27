"""The Params contract: what any caller (CLI, LLM, UI) may send, and the engine's pixel budget."""

import pytest
from PIL import Image

from badshop.engine import common
from badshop.engine.errors import EngineError
from badshop.tools import REGISTRY
from badshop.tools.runner import run_tool
from memstore import MemoryStore

# The fewest fields each tool needs to validate (image refs are never loaded when validation fails).
BASE = {
    "fetch": {}, "wiki": {"title": "x"}, "emoji": {"emoji": ["joy"]}, "template": {},
    "info": {"image": "a.png"}, "prep": {"image": "a.png"}, "view": {"image": "a.png"},
    "find": {"image": "a.png"}, "text": {"image": "a.png", "text": "hi"}, "cutout": {"image": "a.png"},
    "paste": {"base": "a.png", "piece": "b.png"}, "draw": {"image": "a.png"},
    "censor": {"image": "a.png", "box": [[0, 0, 10, 10]]}, "eyes": {"image": "a.png", "at": [[1, 1]]},
    "filter": {"image": "a.png", "names": ["invert"]}, "warp": {"image": "a.png", "at": [[1, 1, 5]]},
    "flare": {"image": "a.png", "at": [1, 1]}, "sparkle": {"image": "a.png"},
    "watermark": {"image": "a.png"}, "save": {"image": "a.png"}, "deepfry": {"image": "a.png"},
    "animate": {"images": ["a.png"]}, "export": {"image": "a.png"},
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """A parameter that wrongly passes validation must not send a network tool off to the internet."""
    from badshop.engine import sources

    def no_network(url, *args, **kwargs):
        pytest.fail(f"a network request got past validation: {url[:80]}")
    monkeypatch.setattr(sources, "http_get", no_network)


def test_base_params_cover_every_tool():
    assert set(BASE) == set(REGISTRY)
    for name, raw in BASE.items():
        REGISTRY[name].params.model_validate(raw)


def _bad(tool: str, **fields) -> EngineError:
    with pytest.raises(EngineError, match=f"bad parameters for {tool}") as e:
        run_tool(tool, {**BASE[tool], **fields}, MemoryStore())
    return e.value


NON_FINITE = [
    ("eyes", "angle", float("inf")), ("eyes", "angle", "nan"), ("text", "rotate", float("nan")),
    ("paste", "rotate", "inf"), ("paste", "scale", float("inf")), ("paste", "width", "inf"),
    ("animate", "amount", float("inf")), ("warp", "strength", float("nan")), ("find", "min_score", "nan"),
    ("save", "lowres", float("nan")),
]


@pytest.mark.parametrize("tool, field, value", NON_FINITE, ids=lambda v: str(v))
def test_non_finite_numbers_are_rejected(tool, field, value):
    e = _bad(tool, **{field: value})
    assert field in e.hint and "finite" in e.hint


COORDS = [
    ("paste", "at", [10**12, 0]), ("text", "at", [0, -100_001]), ("cutout", "box", [0, 0, 100_001, 10]),
    ("draw", "circle", [[5, 5, 10**9]]), ("eyes", "at", [[1, 1], [2, 200_000]]), ("flare", "at", [-10**6, 0]),
]


@pytest.mark.parametrize("tool, field, value", COORDS, ids=lambda v: str(v))
def test_coordinates_are_bounded(tool, field, value):
    e = _bad(tool, **{field: value})
    assert field in e.hint and "100000" in e.hint


def test_far_off_canvas_is_still_a_coordinate():
    for tool, field, value in [("paste", "at", [-100_000, 100_000]), ("cutout", "box", [-100_000, 0, 100_000, 5]),
                               ("warp", "at", [[0, 0, 100_000]])]:
        REGISTRY[tool].params.model_validate({**BASE[tool], field: value})


# (tool, field, the largest value allowed, one too many). Lists and strings are capped by length.
CAPS = [
    ("text", "size", 4096, 4097),
    ("paste", "width", 10_000, 10_000.5), ("paste", "height", 10_000, 10_001),
    ("paste", "scale", 20, 20.01), ("paste", "repeat", 1000, 1001),
    ("sparkle", "repeat", 1000, 1001), ("flare", "size", 20_000, 20_001),
    ("cutout", "grow", 50, 51), ("cutout", "sticker", 100, 101),
    ("animate", "hold", 100, 101), ("animate", "delay", 10_000, 10_001), ("animate", "amount", 100, 100.5),
    ("text", "text", "x" * 1000, "x" * 1001), ("text", "font", "f" * 1024, "f" * 1025),
    ("watermark", "text", "w" * 200, "w" * 201), ("fetch", "query", "q" * 4096, "q" * 4097),
    ("wiki", "title", "t" * 300, "t" * 301), ("template", "name", "n" * 200, "n" * 201),
    ("emoji", "emoji", ["joy"] * 20, ["joy"] * 21), ("animate", "images", ["a.png"] * 32, ["a.png"] * 33),
    ("filter", "names", ["invert"] * 20, ["invert"] * 21), ("warp", "at", [[1, 1, 5]] * 20, [[1, 1, 5]] * 21),
    ("eyes", "at", [[1, 1]] * 20, [[1, 1]] * 21), ("censor", "box", [[0, 0, 9, 9]] * 50, [[0, 0, 9, 9]] * 51),
    ("draw", "circle", [[1, 1, 1]] * 100, [[1, 1, 1]] * 101), ("draw", "arrow", [[0, 0, 1, 1]] * 100, [[0, 0, 1, 1]] * 101),
    ("draw", "line", [[0, 0, 1, 1]] * 100, [[0, 0, 1, 1]] * 101), ("draw", "rect", [[0, 0, 1, 1]] * 100, [[0, 0, 1, 1]] * 101),
    ("sparkle", "at", [[1, 1]] * 200, [[1, 1]] * 201),
    ("watermark", "names", ["hypercam"] * 20, ["hypercam"] * 21),
    # found by probing every number at 10**12: C-level overflows (draw, eyes, text) and hangs (sparkle, censor)
    ("draw", "width", 1000, 1001), ("eyes", "size", 10_000, 10_001), ("text", "margin", 10_000, 10_001),
    ("sparkle", "size", 20_000, 20_001), ("censor", "block", 1000, 1001),
    ("warp", "strength", 10, 10.5), ("warp", "strength", -10, -10.5),
    ("emoji", "emoji", ["x" * 64], ["x" * 65]), ("text", "color", "c" * 100, "c" * 101),
    ("info", "image", "i" * 4096, "i" * 4097),
]


@pytest.mark.parametrize("tool, field, ok, over", CAPS, ids=lambda v: v if isinstance(v, str) and len(v) < 20 else "")
def test_size_and_count_caps(tool, field, ok, over):
    REGISTRY[tool].params.model_validate({**BASE[tool], field: ok})
    assert field in _bad(tool, **{field: over}).hint


def _store_with(*images: Image.Image) -> tuple[MemoryStore, list[str]]:
    store = MemoryStore()
    return store, [store.add(im, f"{i}.png") for i, im in enumerate(images)]


def test_pixel_budget_stops_a_huge_paste():
    # A thin piece scaled to a legal width, or a legal box times a legal scale, would still be gigantic.
    store, (base, bar) = _store_with(Image.new("RGB", (50, 50)), Image.new("RGBA", (1, 1000), "red"))
    with pytest.raises(EngineError, match=r"that would make a 10000x10000000 image") as e:
        run_tool("paste", {"base": base, "piece": bar, "at": [0, 0], "width": 10_000}, store)
    assert e.value.hint
    with pytest.raises(EngineError, match="that would make a"):
        run_tool("paste", {"base": base, "piece": bar, "fit_box": [0, 0, 100_000, 100_000], "scale": 20}, store)
    with pytest.raises(EngineError, match="that would make a"):
        run_tool("paste", {"base": base, "piece": bar, "repeat": 3, "width": 10_000}, store)


def test_pixel_budget_stops_a_huge_caption():
    store, (ref,) = _store_with(Image.new("RGB", (100, 100)))
    with pytest.raises(EngineError, match="that would make a"):
        run_tool("text", {"image": ref, "text": "W" * 1000, "size": 4096}, store)


def test_pixel_budget_stops_a_huge_sticker(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 10_000)
    store, (ref,) = _store_with(Image.new("RGB", (100, 100), "red"))
    run_tool("cutout", {"image": ref, "no_ai": True, "box": [0, 0, 90, 90], "sticker": 1}, store)  # 94x94
    with pytest.raises(EngineError, match="that would make a 104x104 image"):
        run_tool("cutout", {"image": ref, "no_ai": True, "sticker": 1}, store)


def test_budget_leaves_normal_work_alone():
    store, (base, piece) = _store_with(Image.new("RGB", (600, 400)), Image.new("RGBA", (40, 40), "red"))
    run = run_tool("paste", {"base": base, "piece": piece, "fit_box": [100, 50, 400, 400], "scale": 1.1}, store)
    assert run.result.lines[-1].endswith("385x385 after scaling")
