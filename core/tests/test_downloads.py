"""assets.http_get and assets.cached against a real (local) web server: schemes, redirects, caps."""

import socket
import urllib.error

import pytest

from badshop.engine import assets
from badshop.engine.errors import EngineError
from localweb import canned, response, serve


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
