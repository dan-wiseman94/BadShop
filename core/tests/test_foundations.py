import http.client
import io
import threading

import pytest
from PIL import Image

from badshop.engine import assets, common
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output


def test_engine_error_carries_hint():
    e = EngineError("bad box", hint="use find")
    assert (e.message, e.hint, str(e)) == ("bad box", "use find", "bad box")


def test_output_encodes_png_jpeg_gif():
    im = Image.new("RGB", (8, 8), "red")
    assert Output("result", im, "result.png").encode()[:8] == b"\x89PNG\r\n\x1a\n"
    jpg = Output("saved", im, "final:x", fmt="JPEG", quality=20)
    assert jpg.ext() == ".jpg" and jpg.encode()[:2] == b"\xff\xd8"
    frames = [im.quantize(8), Image.new("RGB", (8, 8), "blue").quantize(8)]
    gif = Output("animated", frames[0], "final:x", fmt="GIF", frames=frames, duration=80)
    assert Image.open(io.BytesIO(gif.encode())).n_frames == 2


def test_engine_result_defaults_are_independent():
    a, b = EngineResult(), EngineResult()
    a.lines.append("x")
    assert b.lines == []


def test_clamp_box_sorts_and_clamps():
    assert common.clamp_box((50, 60, 10, 5), (40, 40)) == (10, 5, 40, 40)


def test_clamp_box_outside_raises_engine_error():
    with pytest.raises(EngineError) as e:
        common.clamp_box((500, 500, 600, 600), (100, 100))
    assert "outside" in e.value.message


def test_rgb_unknown_colour():
    assert common.rgb("#ff0000") == (255, 0, 0)
    with pytest.raises(EngineError):
        common.rgb("not-a-colour")


def test_draw_grid_keeps_size():
    im = Image.new("RGB", (320, 240), "white")
    g = common.draw_grid(im)
    assert g.size == im.size and g.getpixel((100, 5)) != (255, 255, 255)


@pytest.mark.parametrize("mode", ["CMYK", "P", "I;16", "LA", "F"])
def test_load_image_modes(tmp_path, mode):
    src = Image.new(mode, (30, 20))
    ext = {"CMYK": ".jpg", "P": ".gif", "I;16": ".png", "LA": ".png", "F": ".tiff"}[mode]
    path = tmp_path / f"x{ext}"
    src.save(path)
    im = common.load_image(path)
    assert common.to_rgb(im).mode == "RGB" and im.size == (30, 20)


def test_load_image_applies_exif_rotation(tmp_path):
    im = Image.new("RGB", (40, 20), "white")
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90° clockwise on display
    path = tmp_path / "phone.jpg"
    im.save(path, exif=exif)
    assert common.load_image(path).size == (20, 40)


def test_data_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    assert assets.data_dir() == tmp_path / "d"


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
    with pytest.raises(EngineError) as e:
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

    with pytest.raises(EngineError) as e:
        assets.cached("m.bin", src.as_uri(), progress=cut)
    assert e.value.hint and "internet" in e.value.hint
    assert list((tmp_path / "d").iterdir()) == []


def test_cached_unusable_data_dir_is_engine_error(monkeypatch, tmp_path):
    (tmp_path / "file").write_text("not a directory")
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "file"))
    with pytest.raises(EngineError):
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
