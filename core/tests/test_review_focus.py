"""Review Focus 1 and 2 across every tool: odd image modes and phone photos, and coordinates off the image
or inverted. Each call succeeds or fails with a clean EngineError, never another exception."""

import pytest
from PIL import Image

from badshop.cli.filestore import FileStore
from badshop.engine.errors import EngineError
from badshop.tools import REGISTRY
from badshop.tools.runner import run_tool

W, H = 120, 90  # the upright size of every odd input


def _picture(mode: str = "RGB") -> Image.Image:
    im = Image.new("RGB", (W, H), (40, 90, 200))
    im.paste((250, 200, 40), (30, 20, 90, 70))
    return im.convert(mode)


def _odd(kind: str, folder) -> str:
    """Write an input the way a user's file would arrive, and return its path."""
    if kind == "cmyk.jpg":
        _picture("CMYK").save(folder / kind)
    elif kind == "keyed.gif":  # a palette GIF with a transparent index
        im = _picture().convert("RGBA")
        im.paste((0, 0, 0, 0), (0, 0, 20, 20))
        im.save(folder / kind)
    elif kind == "la.png":
        im = _picture("L").convert("LA")
        im.putalpha(Image.new("L", (W, H), 200))
        im.save(folder / kind)
    elif kind == "sixteen.png":
        Image.new("I;16", (W, H), 32768).save(folder / kind)
    elif kind == "phone.jpg":  # stored sideways with EXIF orientation 6, as phones do
        stored = _picture().transpose(Image.Transpose.ROTATE_90)
        exif = stored.getexif()
        exif[0x0112] = 6
        stored.save(folder / kind, exif=exif)
    return str(folder / kind)


ODD = ["cmyk.jpg", "keyed.gif", "la.png", "sixteen.png", "phone.jpg"]

# Every non-network tool (some twice), with baseline parameters; "{}" is the odd image.
STEPS = [
    ("info", {}), ("prep", {}), ("view", {"grid": True, "max": 64}), ("find", {"detector": "haar"}),
    ("text", {"text": "top\nbottom"}), ("text", {"text": "hi", "style": "wordart", "at": [60, 45]}),
    ("cutout", {"box": [5, 5, 100, 80], "no_ai": True, "sticker": 3}), ("cutout", {"oval": True, "no_ai": True}),
    ("paste", {"base": "{}", "piece": "{}", "at": [10, 10], "width": 40, "rotate": 10}),
    ("draw", {"circle": [[30, 30, 10]], "arrow": [[0, 0, 50, 50]], "line": [[5, 5, 60, 5]], "rect": [[10, 10, 40, 40]]}),
    ("censor", {"box": [[10, 10, 60, 50]]}), ("censor", {"box": [[10, 10, 60, 50]], "style": "blur", "block": 4}),
    ("eyes", {"at": [[30, 30], [60, 30]]}),
    ("filter", {"names": ["emboss", "edges", "contour", "solarize", "posterize", "invert", "grayscale", "sepia",
                          "blur", "sharpen", "oilpaint"]}),
    ("warp", {"at": [[40, 40, 20]]}), ("flare", {"at": [60, 20]}), ("sparkle", {"at": [[20, 20]], "repeat": 3}),
    ("watermark", {"names": ["hypercam", "bandicam", "ifunny", "mematic"], "text": "made in badshop"}),
    ("save", {}), ("save", {"gif": True}), ("save", {"lowres": 0.3}), ("deepfry", {"level": 2}),
    ("animate", {"images": ["{}", "{}"]}), ("animate", {"images": ["{}"], "effect": "zoom", "frames": 3, "hold": 1}),
    ("export", {}),
]


def test_steps_cover_every_local_tool():
    assert {tool for tool, _ in STEPS} == {n for n, spec in REGISTRY.items() if not spec.network}


def _params(tool: str, params: dict, image: str) -> dict:
    filled = {k: ([image if v == "{}" else v for v in val] if isinstance(val, list) and "{}" in val
                  else image if val == "{}" else val) for k, val in params.items()}
    if tool not in ("paste", "animate"):
        filled["image"] = image
    return filled


class _ClosingStore(FileStore):
    """The CLI's store, closing what it loaded once the test is done: a GIF keeps its file open for
    later frames (accepted for the one-shot CLI), and the test must not leak it."""

    def __init__(self, *args):
        super().__init__(*args)
        self.loaded: list[Image.Image] = []

    def load(self, ref: str) -> Image.Image:
        self.loaded.append(super().load(ref))
        return self.loaded[-1]


@pytest.fixture
def store(tmp_path):
    s = _ClosingStore(tmp_path / "work", tmp_path / "final")
    yield s
    for im in s.loaded:
        im.close()


@pytest.mark.parametrize("kind", ODD)
@pytest.mark.parametrize("tool, params", STEPS, ids=[f"{t}{i}" for i, (t, _) in enumerate(STEPS)])
def test_every_tool_takes_odd_modes_and_phone_photos(tmp_path, store, tool, params, kind):
    # Review Focus 1: every tool treats these as the upright RGB(A) picture; none fails on them.
    image = _odd(kind, tmp_path)
    run = run_tool(tool, _params(tool, params, image), store)
    if tool == "info":
        assert run.result.data == {"width": W, "height": H}  # upright, whatever the stored orientation


@pytest.mark.models
@pytest.mark.parametrize("kind", ODD)
def test_the_background_remover_takes_odd_modes(tmp_path, store, kind):
    image = _odd(kind, tmp_path)
    try:
        run_tool("cutout", {"image": image, "box": [5, 5, 100, 80]}, store)
    except EngineError as e:  # a flat test picture may have no subject to keep
        assert e.message.startswith("nothing was kept"), e.message


FAR = 100_000
# Review Focus 2: points and boxes off the image, inverted, or degenerate, for every tool that takes one.
PLACES = [
    ("cutout", {"box": [100, 80, 5, 5], "no_ai": True}), ("cutout", {"box": [500, 500, 600, 600], "no_ai": True}),
    ("cutout", {"box": [-50, -50, 50, 50], "oval": True}), ("cutout", {"box": [10, 10, 11, 11], "no_ai": True}),
    ("paste", {"at": [-FAR, -FAR], "width": 40}), ("paste", {"at": [FAR, FAR], "width": 40, "anchor": "bottom"}),
    ("paste", {"fit_box": [100, 80, 5, 5]}), ("paste", {"fit_box": [1000, 1000, 2000, 2000], "scale": 0.5}),
    ("paste", {"fit_box": [-FAR, -FAR, FAR, FAR], "scale": 0.001}),
    ("paste", {"repeat": 5, "width": 20, "region": [100, 80, 5, 5]}),
    ("paste", {"repeat": 5, "width": 20, "region": [500, 500, 600, 600]}),
    ("text", {"text": "hi", "at": [-1000, 50]}), ("text", {"text": "hi", "at": [FAR, -FAR], "rotate": 45}),
    ("draw", {"circle": [[FAR, FAR, 10], [10, 10, 0], [10, 10, FAR]]}),
    ("draw", {"arrow": [[100, 80, 5, 5], [5, 5, 5, 5], [-FAR, 0, FAR, 0]]}),
    ("draw", {"rect": [[100, 80, 5, 5], [FAR, FAR, -FAR, -FAR]], "line": [[0, 0, 0, 0]]}),
    ("censor", {"box": [[100, 80, 5, 5], [-10, -10, 30, 30]]}), ("censor", {"box": [[500, 500, 600, 600]]}),
    ("censor", {"box": [[100, 80, 5, 5]], "style": "bar"}), ("censor", {"box": [[-FAR, -FAR, FAR, FAR]], "style": "blur"}),
    ("eyes", {"at": [[-FAR, 5], [FAR, FAR]]}), ("eyes", {"at": [[0, 0]], "angle": -720}),
    ("warp", {"at": [[FAR, FAR, 50]]}), ("warp", {"at": [[10, 10, 0]]}), ("warp", {"at": [[10, 10, FAR]]}),
    ("warp", {"at": [[-5, -5, 30]], "strength": -1}),
    ("flare", {"at": [-FAR, FAR]}), ("flare", {"at": [0, 0], "size": 2}),
    ("sparkle", {"at": [[-FAR, FAR]]}), ("sparkle", {"repeat": 4, "region": [100, 80, 5, 5]}),
    ("sparkle", {"repeat": 4, "region": [500, 500, 600, 600]}),
    ("animate", {"effect": "zoom", "at": [FAR, FAR]}), ("animate", {"effect": "zoom", "at": [-FAR, 0], "amount": 1}),
]


@pytest.mark.parametrize("tool, params", PLACES, ids=[f"{t}{i}" for i, (t, _) in enumerate(PLACES)])
def test_coordinates_off_the_image_or_inverted(tmp_path, store, tool, params):
    image = str(tmp_path / "pic.png")
    _picture().save(image)
    params = {**params, **({"images": [image]} if tool == "animate" else {"image": image})}
    if tool == "paste":
        params = {"base": params.pop("image"), "piece": image, **params}
    try:
        run_tool(tool, params, store)
    except EngineError as e:
        assert e.message and "Traceback" not in e.message
