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

    def openverse_down(url, *args, **kwargs):
        if "api.openverse.org" in url:
            raise urllib.error.URLError("no route to host")
        return served(url, *args, **kwargs)
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
    def missing(url, *args, **kwargs):
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
    def down(url, *args, **kwargs):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(sources, "http_get", down)
    with pytest.raises(EngineError) as e:
        run_tool("fetch", {"query": "golden retriever"}, MemoryStore())
    assert e.value.hint and "internet" in e.value.hint


def test_fetch_url_offline(monkeypatch):
    def down(url, *args, **kwargs):
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


# --- only http(s) links are fetched (SEC-S2) ---

def test_og_image_pointing_at_a_local_file_is_never_fetched(monkeypatch):
    requested = []
    served = fake_http(requested)

    def get(url, timeout=30, max_bytes=None):
        if url.endswith(".html"):
            requested.append(url)
            return b'<html><head><meta property="og:image" content="file:///etc/hostname"></head></html>', "text/html"
        return served(url, timeout)
    monkeypatch.setattr(sources, "http_get", get)
    with pytest.raises(EngineError, match="preview image"):
        run_tool("fetch", {"query": "https://example.org/page.html"}, MemoryStore())
    assert requested == ["https://example.org/page.html"]


def test_page_image_skips_non_web_links():
    html = ('<meta property="og:image" content="file:///etc/x.png">'
            '<meta property="og:image:url" content="http://[oops/x.png">'
            '<meta name="twitter:image" content="javascript:alert(1)">'
            '<link rel="image_src" href="/pics/real.png">')
    assert sources.page_image(html, "https://e.org/a/b.html") == "https://e.org/pics/real.png"
    assert sources.page_image('<meta property="og:image" content="data:image/png;base64,AAAA">', "https://e.org/") is None


def test_fetch_url_refuses_non_web_links(web):
    for url in ("file:///etc/hostname", "ftp://e.org/x.png", "data:image/png;base64,AAAA"):
        with pytest.raises(EngineError, match="only http and https"):
            sources.fetch_url(url)
    assert web == []


def test_candidates_with_non_web_links_fall_back(web):
    hits = [{"title": "sneaky", "url": "file:///etc/hostname", "fallback": "https://e.org/thumb.png"},
            {"title": "sneakier", "url": "ftp://e.org/x.png"}]
    r = sources.download_candidates(hits, "x")
    assert [o.key for o in r.outputs] == ["1"]
    assert r.lines[0].startswith("1: file:///etc/hostname failed (only http and https")
    assert r.lines[1:] == ["2: ftp://e.org/x.png failed (only http and https links can be fetched)",
                           "2: skipped, no usable image"]
    assert web == ["https://e.org/thumb.png"]


# --- size caps (SEC-S3) ---

def test_api_replies_are_capped_at_5_mb(monkeypatch):
    calls = []
    served = fake_http([])

    def get(url, timeout=30, max_bytes=None):
        calls.append((url, max_bytes))
        return served(url, timeout)
    monkeypatch.setattr(sources, "http_get", get)
    run_tool("fetch", {"query": "golden retriever", "n": 1}, MemoryStore())
    run_tool("wiki", {"title": "Abraham Lincoln", "n": 1}, MemoryStore())
    run_tool("template", {"name": "drake", "n": 1}, MemoryStore())
    apis = (sources.COMMONS_API, sources.OPENVERSE_API, sources.IMGFLIP_API, "https://en.wikipedia.org/w/api.php")
    assert sorted(m for u, m in calls if u.startswith(apis)) == [5 * 2**20] * 4
    assert {m for u, m in calls if not u.startswith(apis)} == {None}  # images keep http_get's 40 MB default


def test_page_links_past_the_first_5_mb_are_not_parsed(monkeypatch):
    late = b"<!--" + b"x" * (5 * 2**20) + b'--><meta property="og:image" content="/late.png">'

    def get(url, timeout=30, max_bytes=None):
        return (b"<html><head>" + late + b"</head></html>", "text/html") if url.endswith(".html") else \
            ((FIXTURES / "lincoln.png").read_bytes(), "image/png")
    monkeypatch.setattr(sources, "http_get", get)
    with pytest.raises(EngineError, match="preview image"):
        sources.fetch_url("https://example.org/huge.html")


def test_a_huge_original_falls_back_to_its_thumbnail(monkeypatch, web):
    from test_downloads import pixel_bomb_png
    served = sources.http_get
    monkeypatch.setattr(sources, "http_get", lambda url, *a, **k: (pixel_bomb_png(9000, 8000), "image/png")
                        if url.endswith("/original.png") else served(url, *a, **k))
    r = sources.download_candidates([{"title": "big", "url": "https://e.org/original.png",
                                      "fallback": "https://e.org/thumb.png"}], "x")
    assert [o.key for o in r.outputs] == ["1"] and r.outputs[0].image.size == (457, 600)
    assert r.lines == ["1: https://e.org/original.png failed (that image is too big to fetch "
                       "(Image size (9000x8000) exceeds limit of 64000000 pixels))"]
