import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from memstore import MemoryStore


@pytest.mark.models
def test_cutout_rembg_parity(pair):
    args = ["cutout", "trump.png", "--box", "120", "40", "480", "560"]
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("badshop_work/trump_cutout.png")


@pytest.mark.parametrize("extra", [["--oval"], ["--oval", "--sticker", "8"], ["--no-ai", "--sticker", "5",
                                                                              "--sticker-color", "yellow"]])
def test_cutout_no_model_parity(pair, extra):
    args = ["cutout", "trump.png", "--box", "150", "150", "450", "450", *extra, "-o", "c.png"]
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("c.png")


PASTES = [
    ["--fit-box", "100", "50", "400", "400", "--scale", "1.1", "--rotate", "3"],
    ["--at", "300", "580", "--anchor", "bottom", "--width", "200", "--height", "120", "--flip"],
    ["--repeat", "12", "--width", "60", "--region", "0", "300", "600", "600", "--seed", "4"],
]


@pytest.mark.parametrize("args", PASTES)
def test_paste_parity(pair, args):
    for side in (pair.ref, pair.new):
        side("paste", "lincoln.png", "emoji_joy.png", *args)
    pair.assert_same("badshop_work/result.png")


def test_paste_keeps_transparency():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (100, 100), (0, 128, 255)), "base.png")
    piece_im = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    piece_im.putpixel((5, 5), (255, 0, 0, 255))
    piece = store.add(piece_im, "piece.png")
    run = run_tool("paste", {"base": base, "piece": piece, "at": [0, 0], "width": 10}, store)
    out = store.images[run.refs[0]]
    assert out.getpixel((0, 0)) == (0, 128, 255) and out.getpixel((5, 5)) == (255, 0, 0)


def test_paste_off_canvas():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (50, 50), "white"), "b.png")
    piece = store.add(Image.new("RGBA", (10, 10), "red"), "p.png")
    run = run_tool("paste", {"base": base, "piece": piece, "at": [-5000, -5000], "width": 10}, store)
    assert store.images[run.refs[0]].getpixel((0, 0)) == (255, 255, 255)


def test_paste_needs_placement():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (50, 50)), "b.png")
    piece = store.add(Image.new("RGBA", (10, 10)), "p.png")
    with pytest.raises(EngineError) as e:
        run_tool("paste", {"base": base, "piece": piece}, store)
    assert "width" in e.value.message


def test_cutout_box_outside():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError):
        run_tool("cutout", {"image": ref, "box": [100, 100, 200, 200], "no_ai": True}, store)


def test_cutout_inverted_box():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50), "red"), "x.png")
    run = run_tool("cutout", {"image": ref, "box": [40, 40, 10, 10], "no_ai": True}, store)
    assert store.images[run.refs[0]].size == (30, 30)


def test_cutout_rejects_unlisted_model():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError):
        run_tool("cutout", {"image": ref, "model": "bria-rmbg"}, store)
