"""Model-dependent background removal with unusual image modes and phone orientation."""


import pytest
from PIL import Image

from badshop.cli.filestore import FileStore
from badshop.engine.errors import EngineError
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


@pytest.mark.models
@pytest.mark.parametrize("kind", ODD)
def test_the_background_remover_takes_odd_modes(tmp_path, store, kind):
    image = _odd(kind, tmp_path)
    try:
        run_tool("cutout", {"image": image, "box": [5, 5, 100, 80]}, store)
    except EngineError as e:  # a flat test picture may have no subject to keep
        assert e.message.startswith("nothing was kept"), e.message
