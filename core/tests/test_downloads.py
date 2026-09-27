"""assets.http_get and assets.cached against a real (local) web server: schemes, redirects, caps."""

import http.client
import socket
import struct
import time
import urllib.error
import zlib

import pytest

from badshop.cli.filestore import FileStore
from badshop.engine import assets, sources
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
        with pytest.raises(http.client.IncompleteRead):
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
