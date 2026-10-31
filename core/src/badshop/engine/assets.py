"""Where downloaded assets live, and how they get there."""

import hashlib
import http.client
import json
import re
import shutil
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

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

# Called by cached() after every chunk of every download, as (name, bytes so far, total or None), on
# whichever thread is downloading; it must not raise (that aborts the download). The CLI leaves it
# unset; the app forwards it to clients as asset.progress events.
PROGRESS: Callable[[str, int, int | None], None] | None = None

# Optional application stop signal, checked before opening and between reads. Worker processes
# have their own hook; cancelling a provider never changes another download's signal.
CANCEL: Callable[[str], bool] | None = None


class DownloadCancelled(EngineError):
    """A user stopped a transfer; a verified retry can continue its partial bytes."""

    def __init__(self, name: str):
        super().__init__(f"download of {name} was cancelled", hint="retry to resume the download")


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


def _open(url: str, timeout: float, headers: dict[str, str] | None = None):
    _check_hop(url)
    return _OPENER.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}),
                        timeout=timeout)


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


class Pinned(NamedTuple):
    """An asset pinned to one upstream commit, with the bytes it must have."""
    url: str
    sha256: str
    size: int


OFFLINE_HINT = "check the internet connection; it is only downloaded once"


def _not_pinned(name: str, why: str) -> EngineError:
    return EngineError(f"couldn't download {name} ({why})",
                       hint="check the internet connection and try again; "
                            "if it keeps failing, the upstream file changed")


def _hashes(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def _valid_file(path: Path, sha256: str | None, size: int | None, md5: str | None) -> bool:
    if not path.is_file() or (size is not None and path.stat().st_size != size):
        return False
    if sha256 is not None or md5 is not None:
        sha, digest = _hashes(path)
        return (sha256 is None or sha == sha256) and (md5 is None or digest == md5)
    return True


def cached(name: str, url: str, progress: Callable[[int, int | None], None] | None = None,
           sha256: str | None = None, size: int | None = None, md5: str | None = None,
           dest: Path | None = None, cancel: Callable[[], bool] | None = None) -> Path:
    """Fetch an asset atomically, retaining safe HTTP partials for a later retry.

    A retry sends Range and, when available, If-Range (ETag or Last-Modified). Servers ignoring
    ranges restart the file. Bad ranges, size/checksum failures are discarded. Unpinned downloads
    require an upstream validator to resume. Every concurrent writer owns an independent staging
    directory; an idle partial is claimed by atomic rename, never shared. Cancellation is checked
    before the request and between chunks (a stalled socket remains bounded by its 60s timeout).
    """
    path = Path(dest) if dest is not None else data_dir() / name
    work = pending = root = None
    retain = False
    web = urllib.parse.urlsplit(url).scheme in WEB_SCHEMES
    pinned = sha256 is not None or md5 is not None
    metadata = {}

    def stopped():
        if (cancel is not None and cancel()) or (CANCEL is not None and CANCEL(name)):
            raise DownloadCancelled(name)

    def report(done, total):
        if progress:
            progress(done, total)
        if PROGRESS is not None:
            PROGRESS(name, done, total)

    try:
        if _valid_file(path, sha256, size, md5):
            return path
        stopped()
        path.parent.mkdir(parents=True, exist_ok=True)
        root = path.parent / ".badshop-partials"
        root.mkdir(exist_ok=True, mode=0o700)
        identity = hashlib.sha256(json.dumps([path.name, url, sha256, size, md5]).encode()).hexdigest()
        pending = root / identity
        work = root / (identity + "." + uuid.uuid4().hex)
        try:
            pending.rename(work)
        except FileNotFoundError:
            work.mkdir(mode=0o700)
        body = work / "body"
        meta = work / "response.json"
        if meta.is_file():
            try:
                metadata = json.loads(meta.read_text())
                if not isinstance(metadata, dict):
                    metadata = {}
            except (ValueError, OSError):
                metadata = {}
        # Weak ETags cannot be used for If-Range. A published checksum still permits safe resume.
        etag = metadata.get("etag", "")
        validator = (etag if isinstance(etag, str) and not etag.startswith("W/") else "") or metadata.get("modified", "")
        offset = body.stat().st_size if body.is_file() else 0
        if not web or not (pinned or validator) or (size is not None and offset > size):
            offset = 0
        if offset and size == offset and pinned and _valid_file(body, sha256, size, md5):
            stopped()
            os.chmod(body, 0o644)
            os.replace(body, path)
            return path
        # A claimed, previously accepted partial must survive a failed reconnect too.
        # A received response below re-evaluates retention against its own headers.
        retain = bool(offset)
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        if offset and validator:
            headers["If-Range"] = validator
        try:
            response = _open(url, timeout=60, headers=headers)
        except urllib.error.HTTPError as exc:
            if exc.code != 416 or not offset:
                raise
            exc.close()
            # A stale partial or a server without usable ranges: one fresh request only.
            offset = 0
            retain = False
            response = _open(url, timeout=60)
        with response as r:
            retain = False  # validate a new range/entity before keeping any further bytes
            length = _content_length(r.headers)
            total = length
            if getattr(r, "status", None) == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", r.headers.get("Content-Range", ""))
                if (not offset or match is None or int(match[1]) != offset
                        or int(match[2]) < offset or int(match[2]) >= int(match[3])
                        or (length is not None and length != int(match[2]) - offset + 1)):
                    raise _not_pinned(name, "the server returned an invalid download range")
                total = int(match[3])
                if size is not None and total != size:
                    raise _not_pinned(name, f"{total} bytes, expected {size} bytes")
            else:
                offset = 0  # the server ignored Range or If-Range detected a changed entity
            metadata = {"etag": r.headers.get("ETag", ""), "modified": r.headers.get("Last-Modified", "")}
            meta.write_text(json.dumps(metadata))
            retain = web and bool(pinned or (metadata["etag"] and not metadata["etag"].startswith("W/"))
                                  or metadata["modified"])
            done = offset
            if offset:
                report(done, total)
            with body.open("ab" if offset else "wb") as stream:
                while True:
                    stopped()
                    chunk = r.read1(CHUNK)
                    if not chunk:
                        break
                    stream.write(chunk)
                    done += len(chunk)
                    if size is not None and done > size:
                        retain = False
                        raise _not_pinned(name, f"it is bigger than the expected {size} bytes")
                    report(done, total)
                stopped()
            if total is not None and done != total:
                raise EngineError(f"couldn't download {name} (cut short at {done} of {total} bytes)",
                                  hint=OFFLINE_HINT)
            # A completed HTTP response that doesn't match the pin isn't a useful partial.
            retain = False
            if size is not None and done != size:
                raise _not_pinned(name, f"{done} bytes, expected {size} bytes")
            if not _valid_file(body, sha256, size, md5):
                raise _not_pinned(name, "it failed its checksum")
        os.chmod(body, 0o644)
        try:
            os.replace(body, path)
        except OSError:
            if not _valid_file(path, sha256, size, md5):
                raise
    except BaseException as exc:
        keep = (isinstance(exc, (DownloadCancelled, urllib.error.URLError, OSError, TimeoutError,
                                 http.client.HTTPException))
                or (isinstance(exc, EngineError) and "cut short" in exc.message))
        if retain and keep and work is not None and (work / "body").is_file() and (work / "body").stat().st_size:
            try:
                work.rename(pending)
                work = None
            except OSError:
                pass  # another completed/interrupted writer owns the idle partial; keep its bytes
        if isinstance(exc, (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException)):
            raise EngineError(f"couldn't download {name} ({exc})", hint=OFFLINE_HINT) from exc
        raise
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        if root is not None:
            try:
                root.rmdir()
            except OSError:
                pass  # another writer, or an intentionally retained partial, still uses it
    return path


def configure_rembg() -> None:
    """Point rembg's model cache at our data dir, unless the user already chose one. Call before import."""
    home = str(data_dir() / "rembg")
    os.environ.setdefault("REMBG_HOME", home)
    os.environ.setdefault("U2NET_HOME", os.environ["REMBG_HOME"])
