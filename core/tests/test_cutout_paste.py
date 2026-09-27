import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from conftest import assert_same_image
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
    out = pair.check("paste", "lincoln.png", "emoji_joy.png", *args, files=["badshop_work/result.png"])
    assert "after scaling" in out or "copies" in out


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


def test_paste_repeat_needs_width():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (50, 50)), "b.png")
    piece = store.add(Image.new("RGBA", (10, 10), "red"), "p.png")
    with pytest.raises(EngineError) as e:
        run_tool("paste", {"base": base, "piece": piece, "repeat": 3, "fit_box": [0, 0, 20, 20]}, store)
    assert "width" in e.value.message


def test_cutout_model_download_offline(monkeypatch, tmp_path):
    for k in ("REMBG_HOME", "U2NET_HOME"):
        monkeypatch.setenv(k, str(tmp_path / "rembg"))
    for k in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")
    for k in ("NO_PROXY", "no_proxy"):  # so the dead proxy is always used and nothing is really downloaded
        monkeypatch.delenv(k, raising=False)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError) as e:
        run_tool("cutout", {"image": ref}, store)
    assert "internet" in e.value.hint


def test_cutout_corrupt_model_download(monkeypatch):
    # A captive portal answers the first model download with its login page: pooch's hash check fails.
    import rembg

    def portal(model):
        raise ValueError(f"MD5 hash of downloaded file ({model}.onnx) does not match the known hash")
    monkeypatch.setattr(rembg, "new_session", portal)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match="couldn't download the u2net background-removal model") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "internet" in e.value.hint and "does not match" in e.value.message


def _phone_piece(folder):
    """A piece stored landscape (40x20) with EXIF orientation 6, as phones store photos: upright it is a
    20x40 portrait, red on top and blue below. Also its upright copy as a plain PNG."""
    from badshop.engine.common import load_image

    stored = Image.new("RGB", (40, 20), "blue")
    stored.paste((255, 0, 0), (0, 0, 20, 20))  # the left half is the top once turned 90 degrees clockwise
    exif = stored.getexif()
    exif[0x0112] = 6
    stored.save(folder / "phone.jpg", exif=exif, quality=95)
    load_image(folder / "phone.jpg").save(folder / "upright.png")


def test_exif_rotated_paste_pieces_are_pasted_upright(pair):
    # An intended change from the reference, which pasted the stored (sideways) pixels: pieces now load
    # through the store's EXIF-aware loader, like every other image (Review Focus 1).
    _phone_piece(pair.ref_dir)
    _phone_piece(pair.new_dir)
    args = ["paste", "lincoln.png", "phone.jpg", "--at", "10", "10", "--width", "100"]
    assert "100x50 after scaling" in pair.ref(*args).stdout  # the reference: sideways
    assert "100x200 after scaling" in pair.new(*args, "-o", "rotated.png").stdout
    pair.new("paste", "lincoln.png", "upright.png", "--at", "10", "10", "--width", "100", "-o", "plain.png")
    assert_same_image(pair.new_dir / "rotated.png", pair.new_dir / "plain.png")
    with Image.open(pair.new_dir / "rotated.png") as im:
        top, bottom = im.getpixel((60, 30)), im.getpixel((60, 180))
    assert top[0] > 200 > top[2] and bottom[2] > 200 > bottom[0]  # red on top, blue below
