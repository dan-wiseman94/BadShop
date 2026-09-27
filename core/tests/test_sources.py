import io
import subprocess
import urllib.error
import urllib.parse

import pytest
from PIL import EpsImagePlugin, Image

from badshop.engine import sources
from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from conftest import FIXTURES
from memstore import MemoryStore

API = FIXTURES / "api"


def encode(im: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def lincoln_jpeg() -> bytes:
    return encode(Image.open(FIXTURES / "lincoln.png").convert("RGB"), "JPEG")


def lincoln_sideways_jpeg() -> bytes:
    """The upright 457x600 fixture stored landscape with EXIF orientation 6, the way phones store photos."""
    im = Image.open(FIXTURES / "lincoln.png").convert("RGB").transpose(Image.Transpose.ROTATE_90)
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise on display
    return encode(im, "JPEG", exif=exif)


def fake_http(requested: list[str], jpeg: bytes | None = None):
    """Serve recorded API JSON by host, the page fixture for .html, and a fixture image for anything else."""
    def get(url: str, timeout: float = 30, max_bytes: int | None = None):
        requested.append(url)
        if "commons.wikimedia.org/w/api.php" in url:
            return (API / "commons.json").read_bytes(), "application/json"
        if "api.openverse.org" in url:
            return (API / "openverse.json").read_bytes(), "application/json"
        if "wikipedia.org/w/api.php" in url:
            return (API / "wiki.json").read_bytes(), "application/json"
        if "api.imgflip.com" in url:
            return (API / "imgflip.json").read_bytes(), "application/json"
        if url.endswith(".html"):
            return (API / "page.html").read_bytes(), "text/html"
        if "twemoji" in url:
            return (FIXTURES / "emoji_joy.png").read_bytes(), "image/png"
        if urllib.parse.urlparse(url).path.lower().endswith((".jpg", ".jpeg")):
            return jpeg or lincoln_jpeg(), "image/jpeg"
        return (FIXTURES / "lincoln.png").read_bytes(), "image/png"
    return get


@pytest.fixture
def web(monkeypatch):
    requested: list[str] = []
    monkeypatch.setattr(sources, "http_get", fake_http(requested))
    return requested


def test_fetch_interleaves_and_dedupes(web):
    store = MemoryStore()
    run = run_tool("fetch", {"query": "golden retriever", "n": 4}, store)
    keys = [o.key for o in run.result.outputs]
    assert keys == ["1", "2", "3", "4", "sheet"]
    notes = [o.caption for o in run.result.outputs[:4]]
    assert "[commons]" in notes[0] and "[openverse" in notes[1]
    assert run.result.outputs[0].name_hint.startswith("fetch/golden_retriever_1")


def test_fetch_keeps_jpeg_format(web):
    store = MemoryStore()
    run = run_tool("fetch", {"query": "golden retriever", "source": "commons", "n": 1}, store)
    out = run.result.outputs[0]
    assert out.name_hint.endswith("_1.jpg") and out.fmt == "JPEG"
    assert store.images[run.refs[0]].mode == "RGB"
    assert [o.key for o in run.result.outputs] == ["1"]  # one candidate: no contact sheet


def test_fetch_one_source_down_keeps_the_other(monkeypatch, web):
    served = sources.http_get

    def openverse_down(url, timeout=30):
        if "api.openverse.org" in url:
            raise urllib.error.URLError("no route to host")
        return served(url, timeout)
    monkeypatch.setattr(sources, "http_get", openverse_down)
    run = run_tool("fetch", {"query": "golden retriever", "n": 2}, MemoryStore())
    assert [o.key for o in run.result.outputs] == ["1", "2", "sheet"]
    assert run.result.lines[0].startswith("note: openverse search failed (")
    assert run.result.lines[-1].startswith("source: commons = Wikimedia Commons")


def test_fetch_page_url_follows_og_image(web):
    store = MemoryStore()
    run = run_tool("fetch", {"query": "https://example.org/article.html"}, store)
    assert run.result.outputs[0].key == "fetched"
    assert any(u == "https://example.org/images/lincoln.png" for u in web)


def test_wiki_requests_all_page_images(web):
    run = run_tool("wiki", {"title": "Abraham Lincoln", "n": 2}, MemoryStore())
    assert "pilimit=max" in web[0]
    assert run.result.outputs[0].caption.endswith("Abraham Lincoln  [wikipedia lead image]")


@pytest.mark.parametrize("given,code", [("😂", "1f602"), ("🅱️", "1f171"), ("🇺🇸", "1f1fa-1f1f8"),
                                        ("skull", "1f480"), (":joy:", "1f602"), ("1f525", "1f525"),
                                        ("👨‍💻", "1f468-200d-1f4bb")])
def test_emoji_code(given, code):
    assert sources.emoji_code(given) == code


def test_emoji_keeps_transparency(web):
    store = MemoryStore()
    run = run_tool("emoji", {"emoji": ["😂"], "size": 144}, store)
    im = store.images[run.refs[0]]
    assert im.mode == "RGBA" and im.size == (144, 144) and im.getpixel((0, 0))[3] == 0


def test_emoji_unknown_lists_names(monkeypatch):
    def missing(url, timeout=30):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    monkeypatch.setattr(sources, "http_get", missing)
    with pytest.raises(EngineError) as e:
        run_tool("emoji", {"emoji": ["notanemoji"]}, MemoryStore())
    assert e.value.message == "no emoji downloaded"
    assert "try the emoji character itself, or one of: " in e.value.hint and "skull" in e.value.hint


def test_template_fuzzy_match(web):
    run = run_tool("template", {"name": "distracted", "n": 1}, MemoryStore())
    assert "Distracted Boyfriend" in run.result.outputs[0].caption


def test_template_list(web):
    run = run_tool("template", {"list_all": True}, MemoryStore())
    assert run.refs == [] and any("Drake" in l for l in run.result.lines)


def test_fetch_offline(monkeypatch):
    def down(url, timeout=30):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(sources, "http_get", down)
    with pytest.raises(EngineError) as e:
        run_tool("fetch", {"query": "golden retriever"}, MemoryStore())
    assert e.value.hint and "internet" in e.value.hint


def test_fetch_url_offline(monkeypatch):
    def down(url, timeout=30):
        raise TimeoutError("timed out")
    monkeypatch.setattr(sources, "http_get", down)
    with pytest.raises(EngineError) as e:
        run_tool("fetch", {"query": "https://example.org/pic.png"}, MemoryStore())
    assert e.value.message.startswith("couldn't download https://example.org/pic.png")
    assert "internet" in e.value.hint


def test_clipboard_image(monkeypatch):
    monkeypatch.setattr(sources, "read_clipboard", lambda: ((FIXTURES / "lincoln.png").read_bytes(), None))
    store = MemoryStore()
    run = run_tool("fetch", {"clipboard": True}, store)
    out = run.result.outputs[0]
    w, h = Image.open(FIXTURES / "lincoln.png").size
    assert out.key == "fetched" and out.name_hint.startswith("fetch/clipboard_") and out.name_hint.endswith(".png")
    assert store.images[run.refs[0]].size == (w, h) and run.result.lines == [f"size: {w}x{h}"]


def test_clipboard_link(monkeypatch, web):
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "https://example.org/pic.png"))
    run = run_tool("fetch", {"clipboard": True}, MemoryStore())
    assert run.result.outputs[0].key == "fetched" and web[-1] == "https://example.org/pic.png"


def test_clipboard_empty(monkeypatch):
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "just some words"))
    with pytest.raises(EngineError):
        run_tool("fetch", {"clipboard": True}, MemoryStore())


@pytest.mark.network
def test_live_wiki(pair):
    out = pair.new("wiki", "Abraham Lincoln", "-n", "1").stdout
    assert out.startswith("1: badshop_work/fetch/wiki_abraham_lincoln_1")


# --- downloads decode with the web formats only (SEC-S1), upright (CO I3) ---

EPS = (b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n%%EndComments\n"
       b"newpath 0 0 moveto 10 10 lineto stroke\nshowpage\n%%EOF\n")


def test_downloads_never_reach_the_eps_decoder(monkeypatch):
    # Pretend Ghostscript is installed, so decoding EPS would run it as a subprocess.
    monkeypatch.setattr(EpsImagePlugin, "gs_binary", "gs")
    spawned = []

    def no_subprocess(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("a download started a subprocess")
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, no_subprocess)

    def get(url, timeout=30, max_bytes=None):
        if url.endswith(".html"):
            return b'<html><head><meta property="og:image" content="/art.eps"></head></html>', "text/html"
        return EPS, "application/postscript"
    monkeypatch.setattr(sources, "http_get", get)
    with pytest.raises(EngineError, match="isn't an image"):
        run_tool("fetch", {"query": "https://example.org/page.html"}, MemoryStore())
    assert spawned == []


def test_try_image_decodes_web_formats_only():
    red = Image.new("RGB", (8, 8), "red")
    assert sources.try_image(EPS) is None
    assert sources.try_image(encode(red, "TIFF")) is None
    assert sources.try_image(encode(red, "BMP")) is None
    assert sources.try_image(encode(red, "JPEG")).format == "JPEG"
    mpo = sources.try_image(encode(red, "MPO", save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")]))
    assert mpo.format == "MPO" and mpo.size == (8, 8)  # JPEG's decoder also opens MPO


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP"])
def test_try_image_without_orientation_is_unchanged(fmt):
    data = encode(Image.open(FIXTURES / "lincoln.png").convert("RGB"), fmt)
    plain = Image.open(io.BytesIO(data))
    plain.load()
    im = sources.try_image(data)
    assert (im.format, im.mode, im.size, im.tobytes()) == (plain.format, plain.mode, plain.size, plain.tobytes())


def test_fetched_phone_photos_arrive_upright(monkeypatch):
    monkeypatch.setattr(sources, "http_get", fake_http([], jpeg=lincoln_sideways_jpeg()))
    store = MemoryStore()
    run = run_tool("fetch", {"query": "golden retriever", "source": "commons", "n": 1}, store)
    out = run.result.outputs[0]
    assert out.fmt == "JPEG" and out.name_hint.endswith("_1.jpg")
    assert store.images[run.refs[0]].size == (457, 600) and out.caption.startswith("(457x600) ")
    run = run_tool("fetch", {"query": "https://example.org/IMG_0001.jpg"}, store)
    assert store.images[run.refs[0]].size == (457, 600) and run.result.lines == ["size: 457x600"]


@pytest.mark.parametrize("tool,listing,chosen", [
    ("wl-paste", b"text/html\nimage/bmp\nimage/png\nimage/jpeg\n", "image/png"),
    ("wl-paste", b"image/bmp\nimage/gif\nimage/webp\n", "image/webp"),
    ("wl-paste", b"text/plain\nimage/bmp\n", "image/bmp"),
    ("xclip", b"TARGETS\nimage/tiff\nimage/jpeg\nimage/gif\n", "image/jpeg"),
])
def test_clipboard_prefers_web_image_types(monkeypatch, tool, listing, chosen):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(sources.shutil, "which", lambda name: f"/usr/bin/{name}" if name == tool else None)
    asked = []

    def run(cmd, **kwargs):
        if "--list-types" in cmd or "TARGETS" in cmd:
            out = listing
        else:
            asked.append(cmd[cmd.index("--type" if tool == "wl-paste" else "-t") + 1])
            out = b"image bytes"
        return subprocess.CompletedProcess(cmd, 0, stdout=out)
    monkeypatch.setattr(sources.subprocess, "run", run)
    assert sources.read_clipboard() == (b"image bytes", None)
    assert asked == [chosen]
