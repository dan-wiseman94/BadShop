import json

import pytest
from PIL import Image

from badshop.tools.runner import run_tool
from memstore import MemoryStore
from conftest import FIXTURES


def _lines(out: str) -> list[str]:
    return [l for l in out.splitlines() if not l.startswith("annotated:")]


@pytest.mark.models
@pytest.mark.parametrize("image", ["lincoln.png", "trump.png"])
def test_find_parity(pair, image):
    ref, new = pair.ref("find", image).stdout, pair.new("find", image).stdout
    assert _lines(new) == _lines(ref)
    stem = image.removesuffix(".png")
    pair.assert_same(f"badshop_work/{stem}_faces.png")


@pytest.mark.parametrize("args", [["--detector", "haar"], ["--what", "cats"]])
def test_find_haar_parity(pair, args):
    assert _lines(pair.new("find", "lincoln.png", *args).stdout) == _lines(pair.ref("find", "lincoln.png", *args).stdout)


@pytest.mark.models
def test_find_data_is_json_safe():
    store = MemoryStore()
    ref = store.add(Image.open(FIXTURES / "lincoln.png").convert("RGB"), "lincoln.png")
    run = run_tool("find", {"image": ref}, store)
    faces = run.result.data["faces"]
    assert len(faces) == 1
    json.dumps(faces)
    (x1, y1), (x2, y2) = faces[0]["eyes"]
    assert x1 < x2 and 0 < y1 < 600


@pytest.mark.parametrize("image", ["lincoln.png", "trump.png"])
def test_find_haar_data_is_json_safe(image):
    # Detected Haar eye centres are numpy ints, which json can't encode unconverted. Lincoln's eyes
    # fall back to estimated (plain int) points; trump.png has a face whose eyes the cascade finds.
    store = MemoryStore()
    ref = store.add(Image.open(FIXTURES / image).convert("RGB"), image)
    run = run_tool("find", {"image": ref, "detector": "haar"}, store)
    assert len(run.result.data["faces"]) >= 1
    json.dumps(run.result.data)


def test_find_nothing():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (200, 200), "white"), "blank.png")
    run = run_tool("find", {"image": ref, "detector": "haar"}, store)
    assert run.refs == [] and run.result.lines[0].startswith("nothing found")
