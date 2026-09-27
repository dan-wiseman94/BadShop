"""Where downloaded assets live, and how they get there."""

import http.client
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

import platformdirs

from badshop import __version__
from badshop.engine.errors import EngineError

USER_AGENT = f"badshop/{__version__} (open-source meme tool, run locally by its user)"
CHUNK = 64 * 1024
WEB_SCHEMES = ("http", "https")
MAX_DOWNLOAD = 40 * 2**20  # bytes in any one http_get: a big photo fits, an endless body doesn't

# Called with the first URL of every request and with every redirect hop; it raises (EngineError, say)
# to refuse one. The CLI leaves it unset; the app installs a policy that refuses private addresses.
URL_POLICY: Callable[[str], None] | None = None


def _check_hop(url: str) -> None:
    if URL_POLICY is not None:
        URL_POLICY(url)


class _WebOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects to http(s) links only (urllib's own handler also follows ftp:), and let
    URL_POLICY veto every hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            if urllib.parse.urlsplit(newurl).scheme not in WEB_SCHEMES:
                raise urllib.error.URLError(f"refused a redirect to a non-web link ({newurl[:60]})")
            _check_hop(newurl)
        except BaseException:
            fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_WebOnlyRedirects)


def _open(url: str, timeout: float):
    _check_hop(url)
    return _OPENER.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def data_dir() -> Path:
    env = os.environ.get("BADSHOP_DATA_DIR")
    return Path(env) if env else Path(platformdirs.user_data_dir("badshop", appauthor=False))


def _content_length(headers) -> int | None:
    """The Content-Length header as a number, or None when it is missing or garbage."""
    try:
        n = int(headers.get("Content-Length") or "")
    except ValueError:
        return None
    return n if n >= 0 else None


def _too_big(url: str, max_bytes: int) -> EngineError:
    size = f"{max_bytes / 2**20:g} MB" if max_bytes >= 2**20 else f"{max_bytes} bytes"
    return EngineError(f"{url[:60]} is larger than {size}", hint="use a smaller image or its thumbnail link")


def http_get(url: str, timeout: float = 30, max_bytes: int = MAX_DOWNLOAD) -> tuple[bytes, str]:
    """GET an http(s) link: at most `max_bytes`, all of it within `timeout` seconds (EngineError past
    either). Other schemes (file:, ftp:, data:) raise URLError, even via a redirect."""
    if urllib.parse.urlsplit(url).scheme not in WEB_SCHEMES:
        raise urllib.error.URLError(f"only http and https links can be fetched ({url[:60]})")
    deadline = time.monotonic() + timeout
    with _open(url, min(10, timeout)) as r:  # the socket timeout bounds each recv, not the whole body
        length = _content_length(r.headers)
        if length is not None and length > max_bytes:
            raise _too_big(url, max_bytes)
        body = bytearray()
        # read1 returns what one recv brings; read(n) would wait for all n bytes of a trickle
        while chunk := r.read1(CHUNK):
            body += chunk
            if len(body) > max_bytes:
                raise _too_big(url, max_bytes)
            if time.monotonic() > deadline:
                raise EngineError(f"{url[:60]} took longer than {timeout:g} s",
                                  hint="check the internet connection, or use a local file")
        if length is not None and len(body) < length:  # read1 ends early where read() raised
            raise http.client.IncompleteRead(bytes(body), length - len(body))
        return bytes(body), r.headers.get("Content-Type", "") or ""


def cached(name: str, url: str, progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Download `url` once into data_dir()/name and reuse it. Raises EngineError when offline.

    Each call streams into its own temp file and renames it into place, so concurrent
    downloads of one name (threads or processes) never share a partial file."""
    path = data_dir() / name
    if path.is_file():
        return path
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open(url, timeout=60) as r:  # url is a constant: no scheme check, so tests can use file:
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
            with os.fdopen(fd, "wb") as fh:
                total = int(r.headers.get("Content-Length") or 0) or None
                done = 0
                while chunk := r.read(CHUNK):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        try:
            os.replace(tmp, path)  # atomic; the last complete writer wins
        except OSError:
            if not path.is_file():  # e.g. Windows, where the winner's file may be open
                raise
            Path(tmp).unlink(missing_ok=True)
    except BaseException as e:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        if isinstance(e, (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException)):
            raise EngineError(f"couldn't download {name} ({e})",
                              hint="check the internet connection; it is only downloaded once") from e
        raise
    return path


def configure_rembg() -> None:
    """Point rembg's model cache at our data dir, unless the user already chose one. Call before import."""
    home = str(data_dir() / "rembg")
    os.environ.setdefault("REMBG_HOME", home)
    os.environ.setdefault("U2NET_HOME", os.environ["REMBG_HOME"])
