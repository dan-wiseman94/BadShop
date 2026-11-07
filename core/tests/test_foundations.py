import http.client
import threading

import pytest
from PIL import Image

from badshop.engine import assets, common
from badshop.engine.errors import EngineError


def test_clamp_box_outside_raises_engine_error():
    with pytest.raises(EngineError, match=r"box \(500, 500, 600, 600\) is empty or lies outside the 100x100 image") as e:
        common.clamp_box((500, 500, 600, 600), (100, 100))
    assert "find or a grid view" in e.value.hint


@pytest.mark.parametrize("mode", ["CMYK", "P", "I;16", "LA", "F"])
def test_load_image_modes(tmp_path, mode):
    src = Image.new(mode, (30, 20))
    ext = {"CMYK": ".jpg", "P": ".gif", "I;16": ".png", "LA": ".png", "F": ".tiff"}[mode]
    path = tmp_path / f"x{ext}"
    src.save(path)
    with common.load_image(path) as im:  # a GIF keeps its file open for later frames until closed
        assert common.to_rgb(im).mode == "RGB" and im.size == (30, 20)


@pytest.mark.parametrize("mode, ext", [("I;16", ".png"), ("I;16B", ".tiff")])
def test_16bit_is_scaled_not_clipped(tmp_path, mode, ext):
    # An intended change from the reference, which clipped 16-bit values to 255 (white).
    path = tmp_path / f"deep{ext}"
    Image.new(mode, (4, 4), 32768).save(path)  # mid-grey in 16 bits
    with common.load_image(path) as im:
        assert im.mode == mode
        assert common.to_rgb(im).getpixel((0, 0)) == (128, 128, 128)


def _sideways_jpeg(path):
    im = Image.new("RGB", (40, 20), "white")
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90° clockwise on display
    im.save(path, exif=exif)


def test_load_image_keeps_format(tmp_path):
    # The rotation happens in place, so .format survives: callers read it to pick the file type.
    _sideways_jpeg(tmp_path / "phone.jpg")
    for src in (tmp_path / "phone.jpg", (tmp_path / "phone.jpg").read_bytes()):
        with common.load_image(src) as im:
            assert (im.format, im.size) == ("JPEG", (20, 40))


def test_cached_downloads_once_and_reports_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 5000)
    seen = []
    p = assets.cached("sub/model.bin", src.as_uri(), progress=lambda done, total: seen.append(done))
    assert p.read_bytes() == b"x" * 5000 and seen and seen[-1] == 5000
    src.unlink()  # a second call must not touch the network
    assert assets.cached("sub/model.bin", src.as_uri()) == p


def test_cached_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    with pytest.raises(EngineError, match="couldn't download f.ttf") as e:
        assets.cached("f.ttf", "http://127.0.0.1:9/nothing-listens-here")
    assert e.value.hint and "internet" in e.value.hint
    assert not (tmp_path / "d" / "f.ttf").exists()


def test_cached_concurrent_downloads_of_one_name(monkeypatch, tmp_path):
    # A pauses after 2 chunks, B starts and writes 1 chunk, A finishes, then B finishes.
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    src = tmp_path / "src.bin"
    data = bytes(range(1, 256)) * (5 * assets.CHUNK // 255 + 1)
    src.write_bytes(data)
    a_paused, b_wrote, a_done = threading.Event(), threading.Event(), threading.Event()
    got, errors = {}, {}

    def hook_a(done, total):
        if done == 2 * assets.CHUNK:
            a_paused.set()
            assert b_wrote.wait(10)

    def hook_b(done, total):
        if done == assets.CHUNK:
            b_wrote.set()
            assert a_done.wait(10)

    def run(key, hook):
        try:
            p = assets.cached("m.bin", src.as_uri(), progress=hook)
            got[key] = (p, p.read_bytes())  # read at return time, before the other thread moves on
        except BaseException as e:
            errors[key] = e
        finally:
            if key == "a":
                a_done.set()
            else:
                b_wrote.set()

    ta = threading.Thread(target=run, args=("a", hook_a))
    ta.start()
    assert a_paused.wait(10)
    tb = threading.Thread(target=run, args=("b", hook_b))
    tb.start()
    ta.join(20)
    tb.join(20)
    assert errors == {}
    assert got["a"][1] == data and got["b"][1] == data
    assert got["a"][0] == got["b"][0] and got["a"][0].read_bytes() == data
    assert list((tmp_path / "d").glob("*.part")) == []


def test_cached_failure_mid_download_leaves_no_part_file(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * (3 * assets.CHUNK))

    def cut(done, total):
        raise http.client.IncompleteRead(b"")

    with pytest.raises(EngineError, match="couldn't download m.bin") as e:
        assets.cached("m.bin", src.as_uri(), progress=cut)
    assert e.value.hint and "internet" in e.value.hint
    assert list((tmp_path / "d").iterdir()) == []


def test_cached_unusable_data_dir_is_engine_error(monkeypatch, tmp_path):
    (tmp_path / "file").write_text("not a directory")
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "file"))
    with pytest.raises(EngineError, match="couldn't download sub/m.bin"):
        assets.cached("sub/m.bin", (tmp_path / "file").as_uri())


def test_configure_rembg_sets_home_without_overriding(monkeypatch, tmp_path):
    # set-then-delete so monkeypatch restores whatever was set before this test
    monkeypatch.setenv("REMBG_HOME", "x")
    monkeypatch.delenv("REMBG_HOME")
    monkeypatch.setenv("U2NET_HOME", "x")
    monkeypatch.delenv("U2NET_HOME")
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    assets.configure_rembg()
    import os
    assert os.environ["REMBG_HOME"] == str(tmp_path / "rembg")
    monkeypatch.setenv("REMBG_HOME", "/custom")
    assets.configure_rembg()
    assert os.environ["REMBG_HOME"] == "/custom"
