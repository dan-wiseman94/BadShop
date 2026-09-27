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


@pytest.mark.parametrize("tool, longest", [("prep", 1000), ("view", 1024)])
@pytest.mark.parametrize("size", [(5000, 2), (2, 5000), (3001, 1)])
def test_extreme_aspect_never_rounds_a_side_to_zero(store, tool, size, longest):
    ref = store.add(Image.new("RGB", size, "white"), "strip.png")
    run = run_tool(tool, {"image": ref}, store)
    out = store.images[run.refs[0]]
    assert max(out.size) == longest and min(out.size) == 1


def _labels(monkeypatch):
    """Record every grid label drawn: ((x, y), text)."""
    from badshop.engine import common

    seen, real = [], common.label
    monkeypatch.setattr(common, "label", lambda d, xy, text, fnt: seen.append((xy, text)) or real(d, xy, text, fnt))
    return seen


def test_view_grid_on_a_scaled_image_is_in_source_coordinates(store, monkeypatch):
    # A 2000x1000 image viewed at max 1000 is scaled by 0.5: the gridlines sit every 50 SOURCE px
    # (every 25 view px), the labelled ones every 100 source px, and the labels read source coordinates.
    labels = _labels(monkeypatch)
    ref = store.add(Image.new("RGB", (2000, 1000), "white"), "big.png")
    run = run_tool("view", {"image": ref, "grid": True, "max": 1000}, store)
    out = store.images[run.refs[0]]
    assert out.size == (1000, 500)
    assert run.result.lines == ["size: 1000x500 (scaled 0.500; multiply by 2.000 for source pixels; "
                                "the grid is labelled in source pixels already)"]
    majors = [x for x in range(out.width) if out.getpixel((x, 499)) == (255, 0, 255)]
    minors = [x for x in range(out.width) if out.getpixel((x, 499)) == (255, 170, 255)]
    assert majors == list(range(0, 1000, 50)) and minors == list(range(25, 1000, 50))
    labels = list(dict.fromkeys(labels))  # the x and y labels for 0 share the corner
    assert [(xy[0] - 3, text) for xy, text in labels if xy[1] == 2] == [(x, str(2 * x)) for x in range(0, 1000, 50)]
    assert [(xy[1] - 2, text) for xy, text in labels if xy[0] == 3] == [(y, str(2 * y)) for y in range(0, 500, 50)]


def test_view_grid_thins_labels_that_would_collide(store, monkeypatch):
    # At 0.256 the 100 px labels would sit 25.6 view px apart: they thin to every 200 source px.
    labels = _labels(monkeypatch)
    ref = store.add(Image.new("RGB", (4000, 2000), "white"), "huge.png")
    run = run_tool("view", {"image": ref, "grid": True}, store)
    assert store.images[run.refs[0]].size == (1024, 512)
    top = [(xy[0] - 3, int(text)) for xy, text in dict.fromkeys(labels) if xy[1] == 2]
    assert [v for _, v in top] == list(range(0, 4000, 200))
    assert all(x == round(v * 0.256) for x, v in top)


def test_view_without_grid_keeps_the_plain_note(store):
    ref = store.add(Image.new("RGB", (2000, 1000), "white"), "big.png")
    run = run_tool("view", {"image": ref, "max": 1000}, store)
    assert run.result.lines == ["size: 1000x500 (scaled 0.500; multiply by 2.000 for source pixels)"]


def test_view_grid_unscaled_is_unchanged(store):
    from badshop.engine.common import draw_grid

    im = Image.new("RGB", (640, 480), "white")
    ref = store.add(im, "small.png")
    run = run_tool("view", {"image": ref, "grid": True}, store)
    assert store.images[run.refs[0]].tobytes() == draw_grid(im).tobytes()


class _MaybeImages(Params):
    frames: list[ImageRef] | None = None
    base: ImageRef | None = None
    label: list[str] | None = None


def test_image_fields_optional_list():
    assert registry.image_fields(_MaybeImages) == {"frames": True, "base": False}


def _subschemas(schema: dict):
    """A property's schema and every schema nested in it (anyOf branches, list items)."""
    yield schema
    for s in schema.get("anyOf", []):
        yield from _subschemas(s)
    if isinstance(schema.get("items"), dict):
        yield from _subschemas(schema["items"])


CONVENTION = {"badshop-point": "X Y", "badshop-box": "X1 Y1 X2 Y2", "badshop-spot": "X Y R"}


def test_every_coordinate_says_where_zero_is():
    # Spec 5.2: each schema carries the coordinate convention, so a model never guesses the origin or axes.
    seen = set()
    for spec in registry.REGISTRY.values():
        for name, prop in registry.llm_schema(spec)["properties"].items():
            for s in _subschemas(prop):
                if s.get("format") in CONVENTION:
                    seen.add(s["format"])
                    text = s.get("description", "")
                    assert CONVENTION[s["format"]] in text, (spec.name, name, text)
                    assert "pixels of the image being edited" in text and "top-left" in text, (spec.name, name)
                    assert "y grows downward" in text, (spec.name, name)
    assert seen == set(CONVENTION)


def test_coordinate_fields_keep_their_own_description():
    props = registry.llm_schema(registry.get("flare"))["properties"]
    assert props["at"]["description"].startswith("where the light is. ")


def test_seeds_are_marked_for_a_reroll_control():
    seeds = {(spec.name, name) for spec in registry.REGISTRY.values()
             for name, prop in registry.llm_schema(spec)["properties"].items() if name == "seed"}
    assert seeds == {("paste", "seed"), ("sparkle", "seed"), ("deepfry", "seed"), ("animate", "seed")}
    for tool, name in seeds:
        prop = registry.llm_schema(registry.get(tool))["properties"][name]
        assert prop["format"] == "badshop-seed" and prop["type"] == "integer", tool


def test_seeds_are_still_plain_ints_on_the_cli():
    from badshop.cli.main import build_parser

    a = build_parser().parse_args(["paste", "b.png", "p.png", "--repeat", "3", "--width", "9", "--seed", "-4"])
    assert a.seed == -4


@pytest.mark.parametrize("tool", ["flare", "sparkle", "watermark"])
def test_garnish_says_when_to_use_it(tool):
    assert " Use it " in registry.get(tool).description
