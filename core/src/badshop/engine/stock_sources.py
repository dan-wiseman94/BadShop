"""Optional keyed sources, with bounded responses and Pixabay's 24-hour cache."""

import hashlib
import json
import os
import time
import urllib.parse
import urllib.error
import uuid
from badshop.engine import assets, source_keys
from badshop.engine.errors import EngineError


def search(source, query, n):
    from badshop.engine.discovery import _candidate

    key = source_keys.resolve(source_keys.ENVS[source])
    if not key:
        raise EngineError(
            f"{source} needs an API key", hint=f"set {source_keys.ENVS[source]} or save it in Settings"
        )
    if source == "pexels":
        url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": query, "per_page": n})
        headers = {"Authorization": key}
    elif source == "brave":
        url = "https://api.search.brave.com/res/v1/images/search?" + urllib.parse.urlencode(
            {"q": query, "count": n, "safesearch": "strict"}
        )
        headers = {"X-Subscription-Token": key}
    else:
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
            {"q": query, "key": key, "per_page": max(3, n), "safesearch": "true"}
        )
        headers = {}
    cache = (
        assets.data_dir()
        / "source-previews"
        / (hashlib.sha256((source + "|" + query + "|" + str(n)).encode()).hexdigest() + ".json")
    )
    data = None
    if source == "pixabay":
        try:
            if time.time() - cache.stat().st_mtime < 86400 and cache.stat().st_size < 5 * 2**20:
                data = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if data is None:
        try:
            raw, _ = assets.http_get(url, timeout=10, max_bytes=5 * 2**20, headers=headers)
            data = json.loads(raw)
        except urllib.error.HTTPError as error:
            wait = error.headers.get("Retry-After", "")
            raise EngineError(
                f"{source} returned HTTP {error.code}",
                hint=f"Retry after {wait}." if wait.isdigit() else "check your key or wait before retrying",
            ) from None
        except Exception:
            # Do not expose authenticated URLs, response bodies or keys.
            raise EngineError(
                f"{source} request failed", hint="check the key and connection; no automatic retry was made"
            ) from None
        if source == "pixabay":
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix("." + uuid.uuid4().hex + ".tmp")
            entries = sorted(cache.parent.glob("*.json"), key=lambda p: p.stat().st_mtime)
            used = sum(p.stat().st_size for p in entries)
            for entry in entries:
                if used + len(raw) <= 512 * 2**20:
                    break
                used -= entry.stat().st_size
                entry.unlink(missing_ok=True)
            try:
                tmp.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp, cache)
            finally:
                tmp.unlink(missing_ok=True)
    if source == "pexels":
        return [
            _candidate(
                source,
                r["src"]["large"],
                thumbnail=r["src"]["medium"],
                title=r.get("alt"),
                page=r.get("url"),
                creator=r.get("photographer"),
                license="Pexels License — https://www.pexels.com/license/",
            )
            for r in data.get("photos", [])[:n]
            if r.get("src", {}).get("large")
        ]
    if source == "pixabay":
        return [
            _candidate(
                source,
                r["largeImageURL"],
                thumbnail=r.get("previewURL"),
                title=r.get("tags"),
                page=r.get("pageURL"),
                creator=r.get("user"),
                license="Pixabay Content License — https://pixabay.com/service/license-summary/",
            )
            for r in data.get("hits", [])[:n]
            if r.get("largeImageURL")
        ]
    return [
        _candidate(
            source,
            r["properties"]["url"],
            thumbnail=r.get("thumbnail", {}).get("src"),
            title=r.get("title"),
            page=r.get("url"),
        )
        for r in data.get("results", [])[:n]
        if r.get("properties", {}).get("url")
    ]
