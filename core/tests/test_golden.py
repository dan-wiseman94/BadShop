"""Golden outputs (spec 11, 13.1): fixed inputs, parameters and seeds per tool, pinned by SHA-256.

The parity tests run the reference on the same interpreter as the port, so a Pillow, NumPy, OpenCV,
onnxruntime, libjpeg or zlib change moves both sides together and passes. These pin the bytes
themselves: for every file a run writes, the SHA-256 of its encoded bytes (Output.encode(), the
artifact's identity) and of each decoded frame's RGBA pixels, plus the run's lines and data.

When uv.lock moves one of those libraries on purpose, or a pixel change is intended, regenerate
and review the diff:  cd core && uv run python tests/fixtures/make_golden.py"""

import contextlib
import hashlib
import io
import json
import shutil
from importlib.metadata import version
from pathlib import Path

import pytest
from PIL import Image, ImageSequence

from badshop.cli.filestore import FileStore
from badshop.engine import assets, text
from badshop.tools import REGISTRY
from badshop.tools.runner import run_tool
from conftest import FIXTURES

GOLDEN = FIXTURES / "golden.json"
LIBRARIES = ("pillow", "numpy", "opencv-python-headless", "onnxruntime")

L, T, J = "lincoln.png", "trump.png", "emoji_joy.png"
ALL_FILTERS = ["emboss", "edges", "contour", "solarize", "posterize", "invert", "grayscale", "sepia", "blur",
               "sharpen", "oilpaint"]

# id -> (tool, params, needs a downloaded asset). Image parameters name fixture files.
CASES = {
    "info": ("info", {"image": L}, False),
    "prep": ("prep", {"image": T, "max": 300}, False),
    "view-grid": ("view", {"image": L, "grid": True, "max": 300}, False),
    "view-emoji": ("view", {"image": J, "max": 64}, False),
    "find-haar": ("find", {"image": T, "detector": "haar"}, False),
    "find-yunet": ("find", {"image": L}, True),
    "text-impact": ("text", {"image": L, "text": "problem, liburals??\nsecond line"}, True),
    "text-paint": ("text", {"image": L, "text": "hand drawn", "style": "paint", "at": [300, 400], "rotate": 10,
                            "color": "blue"}, True),
    "text-wordart": ("text", {"image": T, "text": "Four score", "style": "wordart", "bottom": True}, True),
    "cutout-rembg": ("cutout", {"image": T, "box": [120, 40, 480, 560]}, True),
    "cutout-oval": ("cutout", {"image": T, "box": [150, 150, 450, 450], "oval": True, "sticker": 8}, False),
    "cutout-no-ai": ("cutout", {"image": L, "box": [50, 50, 300, 300], "no_ai": True, "sticker": 5,
                                "sticker_color": "yellow"}, False),
    "paste-fit-box": ("paste", {"base": L, "piece": J, "fit_box": [100, 50, 400, 400], "scale": 1.1,
                                "rotate": 3}, False),
    "paste-at": ("paste", {"base": T, "piece": J, "at": [300, 580], "anchor": "bottom", "width": 200,
                           "height": 120, "flip": True}, False),
    "paste-repeat": ("paste", {"base": L, "piece": J, "repeat": 12, "width": 60, "region": [0, 300, 457, 600],
                               "seed": 4}, False),
    "draw": ("draw", {"image": L, "circle": [[300, 250, 80]], "arrow": [[450, 550, 350, 350]],
                      "line": [[0, 0, 100, 100]], "rect": [[10, 10, 200, 120]], "color": "lime", "width": 4}, False),
    "censor-pixelate": ("censor", {"image": L, "box": [[150, 160, 260, 200]]}, False),
    "censor-bar": ("censor", {"image": L, "box": [[150, 160, 260, 200], [0, 0, 50, 50]], "style": "bar"}, False),
    "censor-blur": ("censor", {"image": L, "box": [[150, 160, 260, 200]], "style": "blur", "block": 6}, False),
    "eyes": ("eyes", {"image": L, "at": [[165, 182], [243, 179]], "angle": 30, "size": 9, "color": "cyan"}, False),
    "filter": ("filter", {"image": L, "names": ALL_FILTERS}, False),
    "warp": ("warp", {"image": L, "at": [[165, 182, 31], [243, 179, 31]], "strength": 0.8}, False),
    "flare": ("flare", {"image": L, "at": [400, 90]}, False),
    "sparkle": ("sparkle", {"image": L, "at": [[100, 100]], "repeat": 8, "region": [20, 300, 400, 580],
                            "seed": 3}, False),
    "watermark": ("watermark", {"image": T, "names": ["hypercam", "bandicam", "ifunny", "mematic"],
                                "text": "made in badshop", "corner": "tl"}, False),
    "save-jpeg": ("save", {"image": L, "quality": 20, "passes": 3, "name": "s"}, False),
    "save-lowres": ("save", {"image": L, "lowres": 0.3}, False),
    "save-gif": ("save", {"image": T, "gif": True, "colors": 32}, False),
    "deepfry": ("deepfry", {"image": L}, False),
    "deepfry-nuked": ("deepfry", {"image": T, "level": 5, "no_tint": True, "seed": 7}, False),
    "animate-shake": ("animate", {"images": [L], "effect": "shake", "frames": 6, "seed": 2}, False),
    "animate-zoom-fry": ("animate", {"images": [L], "effect": "zoom", "at": [300, 250], "amount": 2.5, "hold": 2,
                                     "fry": 5}, False),
    "animate-two": ("animate", {"images": [L, T], "effect": "flash"}, False),
    "export": ("export", {"image": J, "name": "kept"}, False),
}


PINNED_FONTS = {"impact": "Anton-Regular.ttf", "wordart": "Anton-Regular.ttf", "paint": "ComicNeue-Bold.ttf"}


def _pinned_font(style: str) -> str | None:
    """A caption style's pinned download (sha-checked); None, Pillow's built-in font, for labels."""
    name = PINNED_FONTS.get(style)
    if name is None:
        return None
    pin = text.FONT_DOWNLOADS[name]
    return str(assets.cached(f"fonts/{name}", pin.url, sha256=pin.sha256, size=pin.size))


@contextlib.contextmanager
def pinned_fonts():
    """The same fonts whatever this machine has installed: a system Impact, Arial or DejaVu would
    otherwise change the pixels (the engine prefers installed fonts, as the reference did)."""
    real = text.find_font_file
    text.find_font_file = lambda style, explicit=None: real(style, explicit) if explicit else _pinned_font(style)
    try:
        yield
    finally:
        text.find_font_file = real


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_record(path: Path) -> dict:
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        frames = [_sha(f.convert("RGBA").tobytes()) for f in ImageSequence.Iterator(im)]
        return {"format": im.format, "size": list(im.size), "sha256": _sha(data), "frames": frames}


def _rounded(value):
    """Floats to 3 decimals: YuNet's landmarks come out of SIMD kernels whose last bits differ between
    CPUs (find's roll moved by 1e-5 with OpenCV's optimisations off; its pixels did not move)."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def run_case(case_id: str, folder: Path) -> dict:
    """Run one case in an empty folder, as the CLI store would, and describe what it produced."""
    tool, params, _ = CASES[case_id]
    for name in {L, T, J}:
        shutil.copy(FIXTURES / name, folder / name)
    at = lambda v: str(folder / v) if v in (L, T, J) else v  # noqa: E731
    raw = {k: [at(x) for x in v] if isinstance(v, list) and k == "images" else at(v) for k, v in params.items()}
    store = FileStore(folder / "work", folder / "final")
    with pinned_fonts():
        run = run_tool(tool, raw, store)
    strip = lambda s: s.replace(f"{folder}/", "")  # noqa: E731
    written = sorted(p for d in ("work", "final") for p in (folder / d).rglob("*") if p.is_file())
    return {
        "lines": [strip(line) for line in run.result.lines],
        "data": _rounded(json.loads(strip(json.dumps(run.result.data)))),
        "files": {str(p.relative_to(folder)): _file_record(p) for p in written},
    }


def versions() -> dict[str, str]:
    return {lib: version(lib) for lib in LIBRARIES}


def _golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_cases_cover_every_local_tool():
    assert {tool for tool, _, _ in CASES.values()} == {n for n, s in REGISTRY.items() if not s.network}
    assert set(_golden()["cases"]) == set(CASES)  # no case without a golden, no stale golden


@pytest.mark.parametrize("case_id", [pytest.param(c, marks=[pytest.mark.models] if CASES[c][2] else [])
                                     for c in CASES])
def test_golden(tmp_path, case_id):
    golden = _golden()
    got = run_case(case_id, tmp_path)
    moved = "" if versions() == golden["versions"] else (
        f" (goldens were made with {golden['versions']}, this is {versions()}: if uv.lock moved them on "
        "purpose, regenerate with `uv run python tests/fixtures/make_golden.py` and review the diff)")
    want = golden["cases"][case_id]
    assert got["lines"] == want["lines"], moved
    assert got["data"] == want["data"], moved
    assert list(got["files"]) == list(want["files"]), moved
    for name, record in want["files"].items():
        assert got["files"][name] == record, f"{name}{moved}"
