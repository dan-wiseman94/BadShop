import pytest
from PIL import Image

from badshop.engine.errors import EngineError
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
    with pytest.raises(EngineError):
        registry.get("nope")


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        registry.register(registry.get("info"))


def test_image_fields_and_schema_formats():
    spec = registry.get("prep")
    assert registry.image_fields(spec.params) == {"image": False}
    schema = registry.llm_schema(spec)
    assert schema["properties"]["image"]["format"] == "badshop-image"
    assert "POSITIONAL" not in schema["properties"]


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


def test_bad_params_become_engine_error_with_hint(store):
    ref = store.add(Image.new("RGB", (10, 10)))
    with pytest.raises(EngineError) as e:
        run_tool("prep", {"image": ref, "max": "big"}, store)
    assert "max" in e.value.hint
    with pytest.raises(EngineError):
        run_tool("prep", {"image": ref, "unknown_option": 1}, store)
