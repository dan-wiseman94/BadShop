import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.engine.types import ImageRef, Params
from badshop.tools import registry
from badshop.tools.runner import run_tool
from memstore import MemoryStore


@pytest.fixture
def store():
    return MemoryStore()


def test_basic_tools_registered():
    for name in ("info", "prep", "view"):
        spec = registry.get(name)
        assert spec.summary and len(spec.description) >= 40


def test_unknown_tool():
    with pytest.raises(EngineError) as e:
        registry.get("nope")
    assert e.value.hint == "tools: " + ", ".join(sorted(registry.REGISTRY))
    assert all(name in e.value.hint for name in ("info", "prep", "view"))


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        registry.register(registry.get("info"))


def test_image_fields_and_schema_formats():
    spec = registry.get("prep")
    assert registry.image_fields(spec.params) == {"image": False}
    schema = registry.llm_schema(spec)
    assert schema["properties"]["image"]["format"] == "badshop-image"
    assert "POSITIONAL" not in schema["properties"]


class _ManyImages(Params):
    images: list[ImageRef]
    base: ImageRef
    piece: ImageRef | None = None
    label: str = ""


def test_image_fields_list_and_optional():
    assert registry.image_fields(_ManyImages) == {"images": True, "base": False, "piece": False}
    props = _ManyImages.model_json_schema()["properties"]
    assert props["images"]["items"]["format"] == "badshop-image"


def test_info(store):
    ref = store.add(Image.new("RGB", (30, 20)), "pic.png")
    run = run_tool("info", {"image": ref}, store)
    assert run.result.lines == [f"{ref}: 30x20"] and run.refs == []
    assert run.result.data == {"width": 30, "height": 20}


def test_prep_makes_work_and_grid(store):
    ref = store.add(Image.new("RGB", (3000, 1500), "white"), "big.png")
    run = run_tool("prep", {"image": ref}, store)
    keys = [o.key for o in run.result.outputs]
    assert keys == ["work", "grid"]
    assert store.images[run.refs[0]].size == (1000, 500)
    assert run.result.lines == ["size: 1000x500"]
    assert run.result.outputs[0].name_hint == "{stem}_work.png"


def test_view_caps_size(store):
    ref = store.add(Image.new("RGB", (4000, 2000), "white"), "huge.png")
    run = run_tool("view", {"image": ref, "grid": True}, store)
    assert store.images[run.refs[0]].size == (1024, 512)


def test_view_scaled_says_so(store):
    ref = store.add(Image.new("RGB", (4000, 2000), "white"), "huge.png")
    run = run_tool("view", {"image": ref}, store)
    assert run.result.lines == ["size: 1024x512 (scaled 0.256; multiply by 3.906 for source pixels)"]


def test_view_within_max_is_unscaled(store):
    im = Image.new("RGB", (300, 200), "white")
    im.putpixel((7, 9), (12, 34, 56))
    ref = store.add(im, "small.png")
    run = run_tool("view", {"image": ref}, store)
    out = store.images[run.refs[0]]
    assert run.result.lines == ["size: 300x200"]
    assert out.mode == "RGB" and out.tobytes() == im.tobytes()


def _cutout(mode):
    """A 200x200 cutout: an opaque red square on a transparent green rectangle (hidden RGB stays green)."""
    im = Image.new("RGBA", (200, 200), (0, 200, 0, 0))
    im.paste((255, 0, 0, 255), (120, 120, 160, 160))
    return im.convert(mode)


@pytest.mark.parametrize("mode", ["RGBA", "PA"])
def test_view_grid_keeps_transparency(store, mode):
    ref = store.add(_cutout(mode), "cut.png")
    run = run_tool("view", {"image": ref, "grid": True}, store)
    out = store.images[run.refs[0]]
    assert out.mode == "RGBA" and out.size == (200, 200)
    for xy in ((25, 25), (75, 75), (175, 30), (30, 175)):  # away from gridlines and labels
        assert out.getpixel(xy)[3] == 0, xy
    assert out.getpixel((130, 130)) == (255, 0, 0, 255)  # the cutout itself
    assert out.getpixel((50, 75)) == (255, 170, 255, 255)  # minor gridline, opaque over transparency
    assert out.getpixel((75, 100)) == (255, 0, 255, 255)  # major gridline


def test_view_opaque_palette_stays_rgb(store):
    ref = store.add(Image.new("RGB", (40, 30), "blue").convert("P"), "pal.png")
    run = run_tool("view", {"image": ref}, store)
    assert store.images[run.refs[0]].mode == "RGB"


def test_bad_params_become_engine_error_with_hint(store):
    ref = store.add(Image.new("RGB", (10, 10)))
    with pytest.raises(EngineError) as e:
        run_tool("prep", {"image": ref, "max": "big"}, store)
    assert "max" in e.value.hint
    with pytest.raises(EngineError):
        run_tool("prep", {"image": ref, "unknown_option": 1}, store)
