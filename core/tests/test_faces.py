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


class _FakeYuNet:
    """Stands in for cv2.FaceDetectorYN: detect() returns the given rows (x y w h, 5 landmarks, score)."""

    def __init__(self, rows):
        self.rows = rows

    def create(self, *args, **kwargs):
        return self

    def detect(self, bgr):
        import numpy as np
        return 1, np.array(self.rows, dtype=np.float32)


def _face(x, y, s=40):
    """A plausible upright face row in an s x s box at (x, y)."""
    return [x, y, s, s, x + s / 4, y + s * 3 / 8, x + s * 3 / 4, y + s * 3 / 8, x + s / 2, y + s * 5 / 8,
            x + s * 0.3, y + s * 7 / 8, x + s * 0.7, y + s * 7 / 8, 0.95]


def test_yunet_junk_rows_are_dropped_and_points_clamped(monkeypatch):
    # YuNet returns junk on tiny or featureless images: inf, nan, 1e32, boxes off the image. The reference
    # crashed drawing them (or noted "YuNet unavailable" and fell back); junk rows are now dropped.
    import cv2
    from badshop.engine import assets

    inf, nan = float("inf"), float("nan")
    stretched = _face(130, 10)
    stretched[11] = stretched[13] = 190.0  # mouth near the bottom: the chin lands far below the image
    rows = [
        [inf] + _face(10, 10)[1:], _face(10, 10)[:5] + [nan] + _face(10, 10)[6:],
        _face(10, 10)[:4] + [1e32, 1e32] + _face(10, 10)[6:],
        [0.8, 145.6, 14.4, 16.7, 4.0, 150.7, 5.3, 150.7, 3.6, 153.7, 3.1, 156.0, 5.0, 156.2, 0.9],  # below
        _face(20, 20)[:2] + [-40, -40] + _face(20, 20)[4:],  # negative size
        _face(20, 30), stretched,
    ]
    monkeypatch.setattr(cv2, "FaceDetectorYN", _FakeYuNet(rows))
    monkeypatch.setattr(assets, "cached", lambda *a, **k: "yunet.onnx")
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (200, 100), "white"), "wide.png")
    run = run_tool("find", {"image": ref, "detector": "yunet"}, store)
    faces = run.result.data["faces"]
    assert [f["box"] for f in faces] == [[20, 30, 60, 70], [130, 10, 170, 50]]
    assert not any(l.startswith("note:") for l in run.result.lines)
    assert faces[1]["chin"][1] == 200  # clamped to the image grown by its own height
    for f in faces:
        for x, y in [*f["eyes"], f["nose"], *f["mouth"], f["chin"]]:
            assert -200 <= x <= 400 and -100 <= y <= 200


@pytest.mark.models
def test_find_with_no_score_cutoff_on_a_blank_image():
    # A real junk row: with min_score 0, YuNet puts a face box below this 60x40 grey image (a crash before).
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (60, 40), "gray"), "grey.png")
    run = run_tool("find", {"image": ref, "min_score": 0}, store)
    for f in run.result.data["faces"]:
        x1, y1, x2, y2 = f["box"]
        assert 0 <= x1 <= x2 <= 60 and 0 <= y1 <= y2 <= 40


@pytest.mark.models
def test_find_on_tiny_images_never_crashes():
    for side in range(3, 33):
        store = MemoryStore()
        ref = store.add(Image.new("RGB", (side, side), "white"), "tiny.png")
        run_tool("find", {"image": ref}, store)
