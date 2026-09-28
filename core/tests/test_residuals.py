"""Plan 1's parked residuals: the image budget floor, the GIF still limit, the offline font retry window."""

import io
import struct

import pytest
from PIL import Image

from badshop.engine import assets, common, finish, text
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.tools.runner import run_tool
from memstore import MemoryStore

# --- the work budget never refuses something as big as the user's own image ---


def test_check_size_floor_raises_the_limit_never_lowers_it(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 10_000)
    common.check_size(100, 100)
    with pytest.raises(EngineError, match="that would make a 101x100 image"):
        common.check_size(101, 100)
    common.check_size(200, 100, floor=20_000)
    with pytest.raises(EngineError, match="that would make a 201x100 image") as e:
        common.check_size(201, 100, floor=20_000)
    assert "limit" in e.value.hint
    with pytest.raises(EngineError, match="that would make a 101x100 image"):
        common.check_size(101, 100, floor=5)


def test_paste_may_make_a_piece_as_big_as_the_base(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 10_000)
    store = MemoryStore()
    base = store.add(Image.new("RGB", (200, 200), "white"), "base.png")  # 40,000 px, over the budget
    piece = store.add(Image.new("RGBA", (10, 10), "red"), "piece.png")
    run = run_tool("paste", {"base": base, "piece": piece, "fit_box": [0, 0, 150, 150]}, store)
    assert run.result.lines[-1].endswith("150x150 after scaling")  # over the budget, under the base
    run = run_tool("paste", {"base": base, "piece": piece, "at": [0, 0], "width": 180}, store)
    assert run.result.lines[-1].endswith("180x180 after scaling")
    run_tool("paste", {"base": base, "piece": piece, "repeat": 3, "width": 120}, store)  # up to 180x180
    with pytest.raises(EngineError, match="that would make a 250x250 image"):
        run_tool("paste", {"base": base, "piece": piece, "fit_box": [0, 0, 250, 250]}, store)


def test_render_text_budget_is_the_floor(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 1_000)
    fnt = common.font(40)
    with pytest.raises(EngineError, match="that would make a"):
        text.render_text(["HELLO"], fnt, "impact", "red")
    layer = text.render_text(["HELLO"], fnt, "impact", "red", budget=60_000)
    assert 1_000 < layer.width * layer.height <= 60_000


def test_caption_may_be_as_big_as_its_image(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 1_000)
    monkeypatch.setattr(text, "find_font_file", lambda style, explicit=None: None)  # built-in font, offline
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (300, 200), "white"), "photo.png")  # 60,000 px
    run = run_tool("text", {"image": ref, "text": "hello", "size": 40}, store)
    assert run.result.lines[0].startswith("text: 1 line(s), impact style, font built-in, size 40px")
    with pytest.raises(EngineError, match="that would make a"):
        run_tool("text", {"image": ref, "text": "WWWW WWWW", "size": 200}, store)


# --- a GIF can't hold one picture for longer than 65535 hundredths of a second ---

def _still(colour: str) -> Image.Image:
    return Image.new("RGB", (24, 24), colour).quantize(colors=8)


def test_gif_writer_limit_is_the_one_animate_checks():
    # Pillow merges identical consecutive frames, adding their delays, into one 16-bit hundredths count.
    assert finish.GIF_MAX_STILL_MS == 65_535 * 10
    f = _still("red")
    fits = finish.GIF_MAX_STILL_MS // 10_000  # 65 frames of 10 s
    data = Output("a", f, "x", fmt="GIF", frames=[f] * fits, duration=10_000).encode()
    with Image.open(io.BytesIO(data)) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 650_000)
    with pytest.raises(struct.error):
        Output("a", f, "x", fmt="GIF", frames=[f] * (fits + 1), duration=10_000).encode()


def test_gif_writer_rounds_a_still_down_to_hundredths():
    # The writer stores int(ms / 10), so a still up to 655_359 ms fits (as 655.35 s) and 655_360 ms doesn't.
    f = _still("red")
    data = Output("a", f, "x", fmt="GIF", frames=[f] * 78, duration=8402).encode()  # 655_356 ms
    with Image.open(io.BytesIO(data)) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 655_350)
    with pytest.raises(struct.error):
        Output("a", f, "x", fmt="GIF", frames=[f] * 80, duration=8192).encode()  # 655_360 ms


def test_longest_still_counts_consecutive_identical_frames():
    red, blue = _still("red"), _still("blue")
    assert finish._longest_still([]) == 0
    assert finish._longest_still([red]) == 1
    assert finish._longest_still([red, red.copy(), blue, blue, blue, red]) == 3
    assert finish._longest_still([red, blue, red, blue]) == 1
    recoloured = red.copy()
    recoloured.putpalette([0, 0, 255] * 256)  # the same indices now mean blue: another picture
    assert finish._longest_still([red, recoloured]) == 1


def test_longest_still_merges_like_the_gif_writer_across_palettes():
    # Pillow compares frames whose palettes differ by their colors, so these 66 frames are one 660 s still.
    red = _still("red")
    unused_differ = red.copy()
    unused_differ.putpalette(red.getpalette()[:3] + [7] * 765)  # only unused entries change
    frames = [red] * 33 + [unused_differ] * 33
    assert finish._longest_still(frames) == 66
    with pytest.raises(struct.error):
        Output("a", red, "x", fmt="GIF", frames=frames, duration=10_000).encode()


def _animate(store: MemoryStore, ref: str, **params):
    return run_tool("animate", {"images": [ref], **params}, store)


def test_animate_holds_the_longest_still_a_gif_can_show():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    run = _animate(store, ref, frames=65, delay=10_000)
    with Image.open(io.BytesIO(run.result.outputs[0].encode())) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 650_000)


def test_animate_accepts_a_still_the_gif_writer_rounds_down(pair):
    # 78 x 8402 ms = 655_356 ms is past 655.35 s, but the writer stores it as 65535 hundredths: the reference
    # writes this GIF, so animate must write it too, frame for frame and duration for duration.
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    run = _animate(store, ref, frames=78, delay=8402)
    with Image.open(io.BytesIO(run.result.outputs[0].encode())) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 655_350)
    pair.check("animate", "emoji_joy.png", "--frames", "78", "--delay", "8402", "--name", "a",
               files=["final/a.gif"])


@pytest.mark.parametrize("params", [
    {"frames": 66, "delay": 10_000},
    {"effect": "zoom", "frames": 2, "hold": 100, "delay": 10_000},  # Plan 1 ruling 80's struct.error
    {"frames": 80, "delay": 8192},  # 655_360 ms: the shortest still the writer can't store
], ids=["frames", "hold", "boundary"])
def test_animate_refuses_a_still_longer_than_a_gif_can_show(params):
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    with pytest.raises(EngineError, match="identical frames in a row") as e:
        _animate(store, ref, **params)
    assert e.value.hint == "lower delay, hold or frames"


def test_animate_long_moving_gifs_are_fine():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    run = _animate(store, ref, effect="flash", frames=120, delay=10_000)  # 20 minutes, never standing still
    with Image.open(io.BytesIO(run.result.outputs[0].encode())) as im:
        assert im.n_frames == 120


# --- offline, a caption tries the font download once, not on every auto-size step ---

@pytest.fixture
def offline_font(tmp_path, monkeypatch):
    """The impact style's only candidate is a font download that fails; returns the list of attempts."""
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])
    monkeypatch.setattr(text, "_font_cache", {})
    monkeypatch.setattr(text, "_download_failed_at", {})
    monkeypatch.setitem(text.FONT_CANDIDATES, "impact", ["BadshopTestDownload.ttf"])
    monkeypatch.setitem(text.FONT_DOWNLOADS, "BadshopTestDownload.ttf",
                        assets.Pinned("https://e.org/f.ttf", "0" * 64, 1))
    attempts = []

    def cached(name, url, **kw):
        attempts.append(name)
        raise EngineError(f"couldn't download {name} (offline)")
    monkeypatch.setattr(assets, "cached", cached)
    return attempts


@pytest.fixture
def lookups(monkeypatch):
    """Records every font lookup: caption's auto-size loop makes one per size it tries."""
    seen = []
    find = text.find_font_file
    monkeypatch.setattr(text, "find_font_file",
                        lambda style, explicit=None: seen.append(style) or find(style, explicit))
    return seen


def _long_caption() -> list[str]:
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (440, 300), "white"), "photo.png")
    return run_tool("text", {"image": ref, "text": "so many words in this caption " * 6}, store).result.lines


def test_offline_caption_tries_the_download_once(offline_font, lookups, monkeypatch):
    assert "font built-in" in _long_caption()[0]
    assert len(lookups) >= 3  # the caption shrank through several sizes
    assert offline_font == ["fonts/BadshopTestDownload.ttf"]
    _long_caption()
    assert len(offline_font) == 1  # the next caption is still inside the retry window

    monkeypatch.setattr(text, "DOWNLOAD_RETRY_S", 0.0)
    lookups.clear()
    _long_caption()
    assert len(offline_font) == 1 + len(lookups)  # no window: every lookup tries again


def test_font_download_is_retried_after_the_window(offline_font, tmp_path, monkeypatch):
    assert text.find_font_file("impact") is None
    assert text.find_font_file("impact") is None
    assert len(offline_font) == 1
    key = ("BadshopTestDownload.ttf", str(assets.data_dir()))
    assert key in text._download_failed_at
    text._download_failed_at[key] -= text.DOWNLOAD_RETRY_S  # the window has passed

    def cached(name, url, **kw):  # back online
        offline_font.append(name)
        (tmp_path / "fonts").mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(b"")
        return tmp_path / name
    monkeypatch.setattr(assets, "cached", cached)
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestDownload.ttf")
    assert len(offline_font) == 2
    assert key not in text._download_failed_at  # a success forgets the failure
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestDownload.ttf")
    assert len(offline_font) == 2  # and the answer is remembered
