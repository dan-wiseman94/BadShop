import io
import json
import re
import subprocess
import urllib.error
import urllib.parse
import zlib

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


def first_commons_url() -> str:
    pages = json.loads((API / "commons.json").read_bytes())["query"]["pages"]
    info = min(pages.values(), key=lambda p: p.get("index", 0))["imageinfo"][0]
    return info.get("thumburl") or info["url"]


def openverse_reply(duplicate: bool = False) -> bytes:
    """The recorded Openverse reply; with duplicate=True its first hit is Commons' first hit again (the
    same file indexed by both services), which the interleave must drop."""
    data = json.loads((API / "openverse.json").read_bytes())
    if duplicate:
        data["results"][0]["url"] = first_commons_url()
    return json.dumps(data).encode()


def fake_http(requested: list[str], jpeg: bytes | None = None, duplicate: bool = False):
    """Serve recorded API JSON by host, the page fixture for .html, and a fixture image for anything else."""
    def get(url: str, timeout: float = 30, max_bytes: int | None = None):
        requested.append(url)
        if "commons.wikimedia.org/w/api.php" in url:
            return (API / "commons.json").read_bytes(), "application/json"
        if "api.openverse.org" in url:
            return openverse_reply(duplicate), "application/json"
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


def test_fetch_interleaves_and_dedupes(monkeypatch):
    requested: list[str] = []
    monkeypatch.setattr(sources, "http_get", fake_http(requested))
    run = run_tool("fetch", {"query": "golden retriever", "n": 4}, MemoryStore())
    notes = [o.caption for o in run.result.outputs[:4]]
    assert ["[commons]" in n for n in notes] == [True, False, True, False]  # commons, openverse, ...
    assert "[openverse" in notes[1] and "[openverse" in notes[3]
    # Now Openverse's first hit is Commons' first hit again: it is dropped, and Openverse's second
    # hit takes its turn in the interleave.
    requested.clear()
    monkeypatch.setattr(sources, "http_get", fake_http(requested, duplicate=True))
    store = MemoryStore()
    run = run_tool("fetch", {"query": "golden retriever", "n": 4}, store)
    keys = [o.key for o in run.result.outputs]
    assert keys == ["1", "2", "3", "4", "sheet"]
    notes = [o.caption for o in run.result.outputs[:4]]
    assert ["[commons]" in n for n in notes] == [True, True, False, True]
    assert notes[2].startswith("(457x600) Golden Retriever Puppy Swimming  [openverse, ")
    assert requested.count(first_commons_url()) == 1
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
    with pytest.raises(EngineError, match=r"commons search failed \(<urlopen error no route to host>\); "
                                          r"openverse search failed") as e:
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
    with Image.open(FIXTURES / "lincoln.png") as im:
        w, h = im.size
    assert out.key == "fetched" and out.name_hint.startswith("fetch/clipboard_") and out.name_hint.endswith(".png")
    assert store.images[run.refs[0]].size == (w, h) and run.result.lines == [f"size: {w}x{h}"]


def test_clipboard_link(monkeypatch, web):
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "https://example.org/pic.png"))
    run = run_tool("fetch", {"clipboard": True}, MemoryStore())
    assert run.result.outputs[0].key == "fetched" and web[-1] == "https://example.org/pic.png"


def test_clipboard_empty(monkeypatch):
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "just some words"))
    with pytest.raises(EngineError, match="the clipboard has no image or link") as e:
        run_tool("fetch", {"clipboard": True}, MemoryStore())
    assert e.value.hint == "copy an image (or its address) and try again"


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


# --- malformed links, damaged Imgflip items, 16-bit images, control characters (TRI T12, CO M5, SEC-S11) ---

@pytest.mark.parametrize("url", ["http://[::1", "http://example.com/a b.png", "http://example.com:port/x.png"])
def test_malformed_links_are_clean_errors(url):
    with pytest.raises(EngineError, match=re.escape(f"{url} isn't a valid link")) as e:
        run_tool("fetch", {"query": url}, MemoryStore())  # urllib refuses these before connecting
    assert "address" in e.value.hint


def test_page_image_skips_a_malformed_link():
    assert sources.page_image('<meta property="og:image" content="http://[oops/x.png">', "https://e.org/") is None


@pytest.mark.parametrize("params", [{"list_all": True}, {"name": "drake"}])
@pytest.mark.parametrize("key", ["name", "url", "width", "height", "box_count"])
def test_template_with_a_damaged_item_is_a_clean_error(monkeypatch, params, key):
    data = json.loads((API / "imgflip.json").read_bytes())
    del data["data"]["memes"][3][key]
    monkeypatch.setattr(sources, "http_get", lambda url, *a, **k: (json.dumps(data).encode(), "application/json"))
    with pytest.raises(EngineError, match="Imgflip template list failed"):
        run_tool("template", params, MemoryStore())


def test_16bit_downloads_are_scaled_like_files(monkeypatch):
    deep = encode(Image.new("I;16", (4, 4), 32768), "PNG")  # mid-grey in 16 bits
    served = fake_http([])
    monkeypatch.setattr(sources, "http_get", lambda url, *a, **k: (deep, "image/png") if "thumb" in url
                        or url.endswith("deep.png") else served(url, *a, **k))
    store = MemoryStore()
    run = run_tool("fetch", {"query": "https://example.org/deep.png"}, store)
    assert store.images[run.refs[0]].getpixel((0, 0)) == (128, 128, 128)
    run = run_tool("fetch", {"query": "golden retriever", "source": "commons", "n": 2}, store)
    first, sheet = (store.images[ref] for ref in (run.refs[0], run.refs[-1]))
    assert first.getpixel((0, 0)) == (128, 128, 128)
    assert run.result.outputs[-1].key == "sheet" and sheet.getpixel((150, 150)) == (128, 128, 128)


CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
EVIL = "cat\x1b[2K\rFAKE LINE\x07\x9b"


def test_remote_control_characters_never_reach_the_terminal(monkeypatch):
    openverse = {"results": [{"url": "https://e.org/a.png", "title": EVIL, "license": "by\x1b", "creator": "x\x07"},
                             {"url": "https://e.org/404.png", "title": EVIL}]}
    imgflip = {"data": {"memes": [{"name": EVIL, "url": "https://e.org/m.png", "width": 1, "height": 1,
                                   "box_count": "2\r"}]}}

    def get(url, *args, **kwargs):
        if "api.openverse.org" in url:
            return json.dumps(openverse).encode(), "application/json"
        if "api.imgflip.com" in url:
            return json.dumps(imgflip).encode(), "application/json"
        if url.endswith(".html"):
            name = "404" if "gone" in url else "pic"
            return f'<meta property="og:image" content="/{name}{EVIL}.png">'.encode(), "text/html"
        if "404" in url:
            raise urllib.error.HTTPError(url, 404, "Not\x1b[2KFound", None, None)
        return (FIXTURES / "lincoln.png").read_bytes(), "image/png"
    monkeypatch.setattr(sources, "http_get", get)
    store = MemoryStore()
    texts = []
    for params in ({"query": "cats", "source": "openverse", "n": 2}, {"query": "https://e.org/page.html"}):
        run = run_tool("fetch", params, store)
        texts += run.result.lines + [o.caption for o in run.result.outputs]
    texts += run_tool("template", {"list_all": True}, store).result.lines
    texts += [o.caption for o in run_tool("template", {"name": "cat", "n": 1}, store).result.outputs]
    for params in ({"query": "https://e.org/gone.html"}, {"query": "gone", "source": "openverse", "n": 1}):
        openverse["results"] = openverse["results"][1:]  # the second round only has the failing hit
        with pytest.raises(EngineError) as e:
            run_tool("fetch", params, store)
        texts += [e.value.message, e.value.hint or ""]
    assert "(457x600) cat [2K FAKE LINE    [openverse, BY , by x ]" in texts
    assert [t for t in texts if CONTROL.search(t)] == []


# --- offline parity with the reference: both CLIs in-process, on one fake web ---

def _parity_images() -> dict[str, bytes]:
    lincoln = Image.open(FIXTURES / "lincoln.png").convert("RGB")
    trump = Image.open(FIXTURES / "trump.png").convert("RGB")
    joy = Image.open(FIXTURES / "emoji_joy.png")
    return {"lincoln.jpg": encode(lincoln, "JPEG"), "trump.jpg": encode(trump, "JPEG"),
            "lincoln.png": (FIXTURES / "lincoln.png").read_bytes(),
            "1f602": (FIXTURES / "emoji_joy.png").read_bytes(),
            "1f480": encode(joy.transpose(Image.Transpose.FLIP_TOP_BOTTOM), "PNG")}


def parity_web():
    """A fake web for both CLIs: the recorded API replies (Openverse repeating one Commons hit, so the
    interleave dedupes), the page fixture, Twemoji with two known emoji (anything else is a 404), one
    Openverse original that is gone (its thumbnail stands in), and a fixture picture for any other link:
    Lincoln or Trump by the link's checksum, so the candidates differ, as JPEG for .jpg links."""
    images = _parity_images()
    gone = json.loads((API / "openverse.json").read_bytes())["results"][1]["url"]

    def get(url: str, timeout: float = 30, max_bytes: int | None = None):
        if "commons.wikimedia.org/w/api.php" in url:
            return (API / "commons.json").read_bytes(), "application/json"
        if "api.openverse.org/v1/images/?" in url:
            return openverse_reply(duplicate=True), "application/json"
        if "wikipedia.org/w/api.php" in url:
            return (API / "wiki.json").read_bytes(), "application/json"
        if "api.imgflip.com" in url:
            return (API / "imgflip.json").read_bytes(), "application/json"
        if url.endswith(".html"):
            return (API / "page.html").read_bytes(), "text/html"
        if "twemoji" in url:
            code = url.rsplit("/", 1)[1].removesuffix(".png")
            if code not in images:
                raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
            return images[code], "image/png"
        if url == gone:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        path = urllib.parse.urlsplit(url).path.lower()
        if path.endswith((".jpg", ".jpeg")):
            return images[("lincoln.jpg", "trump.jpg")[zlib.crc32(url.encode()) % 2]], "image/jpeg"
        return images["lincoln.png"], "image/png"
    return get


# (argv, whether the port prints the same lines in another order: ruling 5.8 puts a tool's outputs
# first, so a page link, a clipboard link, a failed candidate or a missing emoji moves its line)
SOURCE_PARITY = [
    (["fetch", "golden retriever", "-n", "4"], True),  # a duplicate dropped, a gone original, a thumbnail
    (["fetch", "golden retriever", "--source", "commons", "-n", "2"], False),
    (["fetch", "golden retriever", "--source", "openverse", "-n", "3"], True),
    (["fetch", "https://example.org/article.html"], True),
    (["fetch", "https://example.org/pic.png"], False),
    (["fetch", "https://example.org/photo.jpg", "-o", "mine.png"], False),
    (["fetch", "--clipboard"], False),
    (["wiki", "Abraham Lincoln"], False),
    (["wiki", "Abraham Lincoln", "-n", "2"], False),
    (["emoji", "😂", "skull", "--size", "144"], False),
    (["emoji", "joy", "notanemoji", "1f480"], True),
    (["template", "distracted", "-n", "2"], False),
    (["template", "drake"], False),
    (["template", "--list"], False),
]


def _files(root) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("argv, reordered", SOURCE_PARITY, ids=lambda v: " ".join(v) if isinstance(v, list) else None)
def test_sources_match_the_reference_offline(reference, monkeypatch, tmp_path, capsys, argv, reordered):
    import time

    from badshop.cli import main as cli

    web = parity_web()
    monkeypatch.setattr(sources, "http_get", web)
    monkeypatch.setattr(reference, "http_get", web)
    clipboard = lambda: ((FIXTURES / "trump.png").read_bytes(), None)  # noqa: E731
    monkeypatch.setattr(sources, "read_clipboard", clipboard)
    monkeypatch.setattr(reference, "read_clipboard", clipboard)
    monkeypatch.setattr(time, "strftime", lambda fmt, *a: "120000")  # the clipboard file's name
    out = {}
    for side, main in (("ref", reference.main), ("new", cli.main)):
        (tmp_path / side).mkdir()
        monkeypatch.chdir(tmp_path / side)
        assert main(list(argv)) in (None, 0)
        out[side] = capsys.readouterr().out
    ref, new = out["ref"].splitlines(), out["new"].splitlines()
    assert (sorted(new) == sorted(ref)) if reordered else (new == ref)
    assert new != [] and not any(CONTROL.search(l) for l in new)
    ref_files, new_files = _files(tmp_path / "ref"), _files(tmp_path / "new")
    assert list(new_files) == list(ref_files)
    for name in ref_files:
        assert new_files[name] == ref_files[name], name


def test_candidates_use_the_output_extension_table():
    # One format -> extension table: a candidate's file name and Output.ext() can't drift apart.
    from badshop.engine import result

    assert not hasattr(sources, "FORMAT_EXT")
    assert sources.EXT is result.EXT
