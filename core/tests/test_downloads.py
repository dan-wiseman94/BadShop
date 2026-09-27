"""assets.http_get and assets.cached against a real (local) web server: schemes, redirects, caps."""

import hashlib
import http.client
import re
import socket
import stat
import struct
import time
import urllib.error
import zlib

import pytest

from badshop.cli.filestore import FileStore
from badshop.engine import assets, faces, sources, text
from badshop.engine.errors import EngineError
from localweb import canned, response, serve, trickle


def pixel_bomb_png(w: int, h: int) -> bytes:
    """A valid 1-bit PNG of w x h black pixels: kilobytes as a file, w*h bytes once decoded."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = (b"\0" * (1 + (w + 7) // 8)) * h
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


# --- only http(s) links, on the first URL and every redirect hop (SEC-S2) ---

def test_http_get_refuses_local_files(tmp_path):
    (tmp_path / "x.png").write_bytes(b"private")
    with pytest.raises(urllib.error.URLError, match="only http and https"):
        assets.http_get((tmp_path / "x.png").as_uri())


def test_http_get_refuses_a_redirect_to_ftp():
    ftp = socket.create_server(("127.0.0.1", 0))
    ftp.settimeout(0.5)
    target = f"ftp://127.0.0.1:{ftp.getsockname()[1]}/x.png"
    with ftp, serve(canned(response(status="302 Found", headers={"Location": target}))) as base:
        with pytest.raises(urllib.error.URLError, match="refused a redirect"):
            assets.http_get(base + "/start", timeout=2)
        with pytest.raises(TimeoutError):
            ftp.accept()  # nothing ever connected to the FTP address


def test_url_policy_sees_the_first_url_and_every_hop(monkeypatch):
    def reply(conn, path):
        if path == "/start":
            conn.sendall(response(status="302 Found", headers={"Location": "/end"}))
        else:
            conn.sendall(response(b"done", headers={"Content-Type": "text/plain"}))
    seen = []
    monkeypatch.setattr(assets, "URL_POLICY", seen.append)
    with serve(reply) as base:
        assert assets.http_get(base + "/start") == (b"done", "text/plain")  # an http hop still works
        assert seen == [base + "/start", base + "/end"]

        def refuse(url):
            if url.endswith("/end"):
                raise EngineError("that link points into the local network")
        monkeypatch.setattr(assets, "URL_POLICY", refuse)
        with pytest.raises(EngineError, match="local network"):
            assets.http_get(base + "/start")


def test_url_policy_also_guards_asset_downloads(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 10)
    seen = []
    monkeypatch.setattr(assets, "URL_POLICY", seen.append)
    assets.cached("m.bin", src.as_uri())
    assert seen == [src.as_uri()]


# --- size and time caps (SEC-S3, CO M4) ---

def test_http_get_refuses_an_oversized_content_length():
    def reply(conn, path):
        conn.sendall(response(headers={"Content-Length": "50000000"}))
        time.sleep(3)
    with serve(reply) as base:
        start = time.monotonic()
        with pytest.raises(EngineError, match="is larger than 40 MB") as e:
            assets.http_get(base + "/huge.png", timeout=5)
        assert time.monotonic() - start < 2
        assert "thumbnail" in e.value.hint


def test_http_get_stops_past_the_byte_cap():
    body = response(b"x" * 5000, headers={"Content-Length": None})  # close-delimited: no size up front
    with serve(canned(body)) as base:
        with pytest.raises(EngineError, match="is larger than 1000 bytes"):
            assets.http_get(base + "/x", max_bytes=1000)
        assert assets.http_get(base + "/x", max_bytes=5000)[0] == b"x" * 5000


def test_http_get_gives_up_on_a_trickle_at_the_deadline():
    with serve(trickle(every=0.2)) as base:
        start = time.monotonic()
        with pytest.raises(EngineError, match="took longer than 1 s") as e:
            assets.http_get(base + "/drip.png", timeout=1)
        assert time.monotonic() - start < 2
        assert "internet" in e.value.hint


def test_http_get_reports_a_cut_short_body():
    with serve(canned(response(b"x" * 10, headers={"Content-Length": "100"}))) as base:
        with pytest.raises(http.client.IncompleteRead, match="10 bytes read, 90 more expected"):
            assets.http_get(base + "/x")


@pytest.mark.parametrize("size", [(9000, 8000), (20000, 10000)])  # over our 64 Mpx cap; over Pillow's limit
def test_try_image_refuses_pixel_bombs(size):
    bomb = pixel_bomb_png(*size)
    assert len(bomb) < 100_000
    start = time.monotonic()
    with pytest.raises(EngineError, match="too big to fetch") as e:
        sources.try_image(bomb)
    assert time.monotonic() - start < 2
    assert "thumbnail" in e.value.hint


def test_filestore_load_refuses_a_pixel_bomb(tmp_path):
    (tmp_path / "bomb.png").write_bytes(pixel_bomb_png(20000, 10000))
    with pytest.raises(EngineError, match="bomb.png is too big to open"):
        FileStore(tmp_path / "work", tmp_path / "final").load(str(tmp_path / "bomb.png"))


# --- asset downloads: complete, the pinned bytes, readable (SEC-S6, TRI M1) ---

@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    return tmp_path / "d"


def test_cached_rejects_a_cut_short_download(data):
    with serve(canned(response(b"x" * 5000, headers={"Content-Length": "100000"}))) as base:
        with pytest.raises(EngineError, match=r"couldn't download fonts/A.ttf \(cut short at 5000 of 100000") as e:
            assets.cached("fonts/A.ttf", base + "/A.ttf")
    assert "internet" in e.value.hint
    assert not any(data.rglob("*.ttf*"))


def test_cached_tolerates_a_garbage_content_length(data):
    with serve(canned(response(b"x" * 50, headers={"Content-Length": "abc"}))) as base:
        assert assets.cached("fonts/A.ttf", base + "/A.ttf").read_bytes() == b"x" * 50


def test_cached_rejects_a_bad_checksum(data, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 10)
    with pytest.raises(EngineError, match="failed its checksum") as e:
        assets.cached("m.bin", src.as_uri(), sha256="0" * 64, size=10)
    assert "upstream file changed" in e.value.hint
    assert not data.exists() or list(data.iterdir()) == []
    good = hashlib.sha256(b"x" * 10).hexdigest()
    assert assets.cached("m.bin", src.as_uri(), sha256=good, size=10).read_bytes() == b"x" * 10


@pytest.mark.parametrize("served", [5, 30])  # too short; longer than pinned (stops reading past the size)
def test_cached_rejects_the_wrong_size(data, tmp_path, served):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * served)
    with pytest.raises(EngineError, match="expected 20 bytes"):
        assets.cached("m.bin", src.as_uri(), size=20)
    assert not data.exists() or list(data.iterdir()) == []


def test_cached_heals_a_short_file(data, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 10)
    (data / "fonts").mkdir(parents=True)
    (data / "fonts" / "A.ttf").write_bytes(b"xxxxx")  # cut short by an earlier version
    assert assets.cached("fonts/A.ttf", src.as_uri(), size=10).read_bytes() == b"x" * 10
    src.unlink()  # now the right size: a cache hit, no download
    assert assets.cached("fonts/A.ttf", src.as_uri(), size=10).read_bytes() == b"x" * 10


def test_cached_files_are_readable_by_everyone(data, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    assert stat.S_IMODE(assets.cached("m.bin", src.as_uri()).stat().st_mode) == 0o644


def test_asset_urls_are_pinned():
    for pin in (faces.YUNET, *text.FONT_DOWNLOADS.values()):
        assert re.search(r"/raw/[0-9a-f]{40}/", pin.url), pin.url  # one upstream commit, not a branch
        assert re.fullmatch(r"[0-9a-f]{64}", pin.sha256) and pin.size > 0
    assert "@latest" not in sources.TWEMOJI_URL and re.search(r"@\d+\.\d+\.\d+/", sources.TWEMOJI_URL)


@pytest.mark.models
def test_pinned_assets_have_their_pinned_bytes():
    # A cache hit here (core/.test-cache has them); a real, verified download on a fresh checkout.
    pins = [("face_detection_yunet_2023mar.onnx", faces.YUNET),
            *((f"fonts/{name}", pin) for name, pin in text.FONT_DOWNLOADS.items())]
    for name, pin in pins:
        path = assets.cached(name, pin.url, sha256=pin.sha256, size=pin.size)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pin.sha256, name
