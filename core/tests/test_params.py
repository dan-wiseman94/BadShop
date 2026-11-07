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
    "layout": {}, "pair_images": {"donors": ["a.png"], "backgrounds": ["b.png"]},
    "slice_sheet": {"image": "a.png"},
    "discover": {"query": "cat"}, "acquire": {"url": "https://example.com/cat.jpg"},
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


def _bad(tool: str, **fields) -> EngineError:
    with pytest.raises(EngineError, match=f"bad parameters for {tool}") as e:
        run_tool(tool, {**BASE[tool], **fields}, MemoryStore())
    return e.value


NON_FINITE = [
    ("eyes", "angle", float("inf")),
    ("eyes", "angle", "nan"),
    ("paste", "rotate", "inf"),
    ("warp", "strength", float("nan")),
]


@pytest.mark.parametrize("tool, field, value", NON_FINITE, ids=lambda v: str(v))
def test_non_finite_numbers_are_rejected(tool, field, value):
    e = _bad(tool, **{field: value})
    assert field in e.hint and "finite" in e.hint


COORDS = [
    ("paste", "at", [10**12, 0]),
    ("cutout", "box", [0, 0, 100_001, 10]),
    ("draw", "circle", [[5, 5, 10**9]]),
]


@pytest.mark.parametrize("tool, field, value", COORDS, ids=lambda v: str(v))
def test_coordinates_are_bounded(tool, field, value):
    e = _bad(tool, **{field: value})
    assert field in e.hint and "100000" in e.hint


# (tool, field, the largest value allowed, one too many). Lists and strings are capped by length.
CAPS = [
    ("text", "size", 4096, 4097),
    ("paste", "width", 10_000, 10_000.5),
    ("paste", "scale", 20, 20.01),
    ("paste", "repeat", 1000, 1001),
    ("cutout", "grow", 50, 51),
    ("animate", "amount", 100, 100.5),
    ("text", "text", "x" * 1000, "x" * 1001),
    ("emoji", "emoji", ["joy"] * 20, ["joy"] * 21),
    ("animate", "images", ["a.png"] * 32, ["a.png"] * 33),
    ("warp", "at", [[1, 1, 5]] * 20, [[1, 1, 5]] * 21),
    ("warp", "strength", -10, -10.5),
    ("emoji", "emoji", ["x" * 64], ["x" * 65]),
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


# --- file names: finished files land in the output folder and nowhere else ---

BAD_NAMES = ["../x", "/tmp/x", "a/b", "..", "C:x", "a\\b", "", ".", "...", " . ", "x\x07y", "tab\tname", "n" * 101]


@pytest.mark.parametrize("tool, name", [("save", name) for name in BAD_NAMES] + [
    ("deepfry", "../x"), ("animate", "../x"), ("export", "../x"),
])
def test_names_must_be_plain_file_names(tool, name):
    e = _bad(tool, name=name)
    assert "name" in e.hint


@pytest.mark.parametrize("name", ["lincoln_lasers", "mona cage é", "v1.2 final", ".hidden", "n" * 100])
def test_plain_names_still_work(name):
    assert REGISTRY["save"].params.model_validate({**BASE["save"], "name": name}).name == name


@pytest.mark.parametrize("stem", ["../x", "a/b", "/abs/x", "", ".", ".."])
def test_final_path_refuses_anything_but_a_plain_stem(tmp_path, stem):
    from badshop.cli.filestore import final_path

    with pytest.raises(EngineError, match="bad file name"):
        final_path(tmp_path / "final", stem, ".png")
    assert not (tmp_path / "x.png").exists()


def test_export_copies_images_only(tmp_path):
    from badshop.cli.filestore import FileStore

    notes = tmp_path / "notes.txt"
    notes.write_text("not an image")
    store = FileStore(tmp_path / "w", tmp_path / "final")
    with pytest.raises(EngineError, match="isn't an image"):
        store.export(str(notes), None)
    assert not (tmp_path / "final").exists() or not any((tmp_path / "final").iterdir())
    pic = tmp_path / "pic.gif"
    Image.new("RGB", (8, 8), "red").save(pic)
    out = store.export(str(pic), "kept")
    assert out == str(tmp_path / "final" / "kept.gif") and (tmp_path / "final/kept.gif").read_bytes() == pic.read_bytes()


# --- text.font: a font file name or path, never a folder walk ---

@pytest.mark.parametrize("font", ["*.ttf", "Dejavu?.ttf", "x[1].ttf", "../../etc/x.ttf", "fonts/../../x.ttf",
                                  "..\\x.ttf", "/usr/share/fonts/../../x.ttf", "**"])
def test_font_rejects_wildcards_and_parent_folders(font):
    assert "font" in _bad("text", font=font).hint


def test_font_lookup_matches_names_literally(tmp_path, monkeypatch):
    # Even called directly (no validation), the folder search treats a name as a file name, not a pattern.
    from badshop.engine import text

    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "xa.ttf").write_bytes(b"")
    (tmp_path / "fonts" / "y[1].ttf").write_bytes(b"")
    assert text.find_font_file("impact", "x[ab].ttf") is None
    assert text.find_font_file("impact", "y[1].ttf") == str(tmp_path / "fonts" / "y[1].ttf")
