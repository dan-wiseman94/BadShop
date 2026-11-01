"""Preview-first image discovery. Ranking is a transparent heuristic, never face identification.

Only a contact sheet is an artifact; candidates stay bounded metadata until acquire is called.
All image bytes continue through the existing downloader/decoder and network policy.
"""

import base64
import hashlib
import io
import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, ClassVar, Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from pydantic import Field, field_validator

from badshop.engine import sources
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import ImageRef, Params

SourceName = Literal["all", "commons", "openverse", "loc", "met", "flickr", "nasa", "web", "smithsonian", "bhl", "europeana", "cleveland", "wellcome"]
URL = Annotated[str, Field(max_length=4096)]

# Configuration presence is useful to the picker without exposing credentials or doing a network check.
SOURCE_CONFIG = {
    "commons": ("Wikimedia Commons", None, False),
    "openverse": ("Openverse", None, False),
    "loc": ("Library of Congress", None, False),
    "met": ("The Met", None, False),
    "nasa": ("NASA", None, False),
    "cleveland": ("Cleveland Museum of Art", None, False),
    "wellcome": ("Wellcome Collection", None, False),
    "flickr": ("Flickr Commons", "BADSHOP_FLICKR_API_KEY", True),
    "smithsonian": ("Smithsonian Open Access", "BADSHOP_SMITHSONIAN_API_KEY", True),
    "bhl": ("Biodiversity Heritage Library", "BADSHOP_BHL_API_KEY", True),
    "europeana": ("Europeana", "BADSHOP_EUROPEANA_API_KEY", True),
    "web": ("Custom image search", "BADSHOP_IMAGE_SEARCH_URL", False),
}


def source_status() -> list[dict]:
    """Public configuration capabilities, not service health or validation of supplied API keys."""
    return [{"id": id, "name": name, "configured": env is None or bool(os.environ.get(env, "").strip()),
             "requires_key": requires_key, "env_var": env}
            for id, (name, env, requires_key) in SOURCE_CONFIG.items()]


class DiscoverParams(Params):
    POSITIONAL: ClassVar = ("query",)
    query: str = Field(min_length=1, max_length=300, description="Subject name or short literal search words")
    source: SourceName = "all"
    n: int = Field(8, ge=1, le=12)
    purpose: Literal["subject", "head", "background", "object"] = "subject"
    pose: str | None = Field(None, max_length=100, description="Desired shot, e.g. facing left, full body")
    expression: str | None = Field(None, max_length=100, description="Desired expression, e.g. screaming")
    same_subject: bool = Field(False, description="Search a named subject's Commons category rather than related Wikipedia articles")
    similar_to: ImageRef | None = Field(None, description="Optional selected image to compare visually")
    reference_url: URL | None = Field(None, description="A discovery candidate's thumbnail URL to compare without importing it")
    variation: Literal["balanced", "similar", "different"] = "balanced"
    exclude_urls: list[URL] = Field(default_factory=list, max_length=50)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("search words cannot be blank")
        return value.strip()


class AcquireParams(Params):
    POSITIONAL: ClassVar = ("url",)
    url: URL
    source_kind: str = Field("url", max_length=50)
    page: URL | None = None
    title: str | None = Field(None, max_length=500)
    license: str | None = Field(None, max_length=500)
    creator: str | None = Field(None, max_length=500)


def _json(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data, _ = sources.http_get(sources._web_url(url), timeout=8, max_bytes=sources.MAX_TEXT)
    return json.loads(data)


def _strings(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value if isinstance(v, str))[:500] or None
    return value[:500] if isinstance(value, str) else None


def _candidate(kind, url, *, thumbnail=None, title=None, page=None, license=None, creator=None):
    if not isinstance(url, str) or len(url) > 4096 or (thumbnail is not None and
            (not isinstance(thumbnail, str) or len(thumbnail) > 4096)):
        raise EngineError("source returned an invalid or oversized image address")
    url = sources._web_url(url)
    thumbnail = sources._web_url(thumbnail or url)
    title = sources._clean(_strings(title) or "Untitled")[:500]
    page = page if isinstance(page, str) and len(page) <= 4096 else None
    try:
        page = sources._web_url(page) if page else None
    except EngineError:
        page = None
    source = sources.provenance(kind, url, page=page, title=title,
                                license=_strings(license), creator=_strings(creator))
    source = {key: sources._clean(value) if isinstance(value, str) else value for key, value in source.items()}
    return {"id": hashlib.sha256(url.encode()).hexdigest()[:16], "title": title, "url": url,
            "thumbnail": thumbnail, "page": source["page"], "source": source}


def commons(query, n):
    data = _json(sources.COMMONS_API, {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": n, "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 320,
        "iiextmetadatafilter": "LicenseShortName|Artist",
    })
    return _commons_hits(data, n)


def _commons_hits(data, n):
    hits = []
    pages = data.get("query", {}).get("pages", {})
    for page in sorted(pages.values(), key=lambda item: item.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in sources.IMAGE_MIMES or not info.get("url"):
            continue
        hits.append(_candidate("commons", info["url"], thumbnail=info.get("thumburl"),
            title=page.get("title", "").removeprefix("File:"), page=info.get("descriptionurl"),
            license=sources.html_text(sources._extmeta(info, "LicenseShortName")),
            creator=sources.html_text(sources._extmeta(info, "Artist"))))
    return hits[:n]


def _subject_collection(query, n):
    """Resolve the exact article's Wikidata Commons category, not neighboring article lead photos."""
    article = _json("https://en.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "titles": query, "redirects": 1, "prop": "pageprops"})
    pages = article.get("query", {}).get("pages", {}).values()
    item = next((p.get("pageprops", {}).get("wikibase_item") for p in pages
                 if p.get("pageprops", {}).get("wikibase_item")), None)
    if item and re.fullmatch(r"Q\d+", item):
        entity = _json("https://www.wikidata.org/w/api.php", {
            "action": "wbgetentities", "format": "json", "ids": item, "props": "claims"})
        claims = entity.get("entities", {}).get(item, {}).get("claims", {}).get("P373", [])
        category = next((c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in claims
                         if isinstance(c.get("mainsnak", {}).get("datavalue", {}).get("value"), str)), None)
        if category:
            data = _json(sources.COMMONS_API, {
                "action": "query", "format": "json", "generator": "categorymembers",
                "gcmtitle": "Category:" + category, "gcmtype": "file", "gcmlimit": n,
                "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 320,
                "iiextmetadatafilter": "LicenseShortName|Artist"})
            hits = _commons_hits(data, n)
            if hits:
                return hits
    # Exact phrase preserves the subject better than Wikipedia article search.
    return commons('"' + query.replace('"', '') + '"', n)


def subject_commons(query, n):
    try:
        return _subject_collection(query, n)
    except (EngineError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return commons('"' + query.replace('"', '') + '"', n)


def openverse(query, n):
    data = _json(sources.OPENVERSE_API, {"q": query, "page_size": n, "mature": "false"})
    return [_candidate("openverse", item["url"], thumbnail=item.get("thumbnail"),
                       title=item.get("title"), page=item.get("foreign_landing_url"),
                       license=sources.openverse_license(item.get("license"), item.get("license_version")),
                       creator=item.get("creator"))
            for item in data.get("results", [])[:n] if item.get("url")]


def loc(query, n):
    data = _json("https://www.loc.gov/photos/", {"fo": "json", "q": query, "c": n})
    hits = []
    for item in data.get("results", [])[:n]:
        urls = [url for url in item.get("image_url", []) if isinstance(url, str) and url.startswith("http")]
        if urls:
            hits.append(_candidate("loc", urls[-1], thumbnail=urls[0], title=item.get("title"),
                page=item.get("url") or item.get("id"), license=_strings(item.get("rights")),
                creator=_strings(item.get("contributor"))))
    return hits


def met(query, n):
    base = "https://collectionapi.metmuseum.org/public/collection/v1/"
    # The unpaginated v1 search was retired October 2026; objects remain at v1.
    data = _json("https://collectionapi.metmuseum.org/public/collection/v1.1/search",
                 {"q": query, "hasImages": "true", "limit": n, "offset": 0})
    ids = [i for i in (data.get("objectIDs") or [])[:n] if isinstance(i, int)]
    def get(item_id):
        try:
            item = _json(base + "objects/" + str(item_id))
            if item.get("isPublicDomain") and item.get("primaryImage"):
                return _candidate("met", item["primaryImage"], thumbnail=item.get("primaryImageSmall"),
                    title=item.get("title"), page=item.get("objectURL"), license="CC0 1.0",
                    creator=item.get("artistDisplayName"))
        except (EngineError, OSError, ValueError, TypeError):
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [hit for hit in pool.map(get, ids) if hit]


def _object(value):
    return value if isinstance(value, dict) else {}


def _objects(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def cleveland(query, n):
    """CC0 artwork images, using manageable print JPEGs rather than archival TIFF downloads."""
    limit = min(24, max(1, n * 2))
    data = _json("https://openaccess-api.clevelandart.org/api/artworks/", {
        "q": query, "cc0": 1, "has_image": 1, "limit": limit,
        "fields": "id,title,url,share_license_status,images,creators",
    })
    hits = []
    for item in _objects(_object(data).get("data"))[:limit]:
        # Metadata are CC0 even when an artwork's image is not; verify image status locally too.
        if item.get("share_license_status") != "CC0":
            continue
        images = _object(item.get("images"))
        preview = _object(images.get("web")).get("url")
        original = _object(images.get("print")).get("url") or preview
        if not original:
            continue
        creators = [creator.get("description") for creator in _objects(item.get("creators"))]
        try:
            hits.append(_candidate("cleveland", original, thumbnail=preview, title=item.get("title"),
                                   page=item.get("url"), license="CC0 1.0", creator=_strings(creators)))
        except EngineError:
            continue  # a malformed address must not discard the rest of this collection
        if len(hits) >= n:
            break
    return hits


WELLCOME_LICENSES = ("cc0", "pdm", "cc-by", "cc-by-sa")


def wellcome(query, n):
    """Open-licensed photos, prints, posters and scientific imagery via the image catalogue."""
    limit = min(24, max(1, n * 2))
    data = _json("https://api.wellcomecollection.org/catalogue/v2/images", {
        "query": query, "pageSize": limit, "include": "source.contributors",
        "locations.license": ",".join(WELLCOME_LICENSES),
    })
    hits = []
    for item in _objects(_object(data).get("results"))[:limit]:
        source = _object(item.get("source"))
        for location in _objects(item.get("locations")):
            license = _object(location.get("license"))
            if (_object(location.get("locationType")).get("id") != "iiif-image"
                    or license.get("id") not in WELLCOME_LICENSES):
                continue
            conditions = _objects(location.get("accessConditions"))
            if conditions and not any(_object(c.get("status")).get("id") in ("open", "open-with-advisory") for c in conditions):
                continue
            info = location.get("url")
            if not isinstance(info, str) or not info.endswith("/info.json"):
                continue
            service = info.removesuffix("/info.json")
            # Preserve the full source image for acquire; only previews request a scaled derivative.
            ratio = item.get("aspectRatio")
            thumb_size = "320," if isinstance(ratio, (int, float)) and ratio >= 1 else ",320"
            contributors = [_object(c.get("agent")).get("label") for c in _objects(source.get("contributors"))]
            creators = list(dict.fromkeys(v for v in [location.get("credit"), *contributors] if isinstance(v, str)))
            id = item.get("id")
            page = "https://wellcomecollection.org/images/" + urllib.parse.quote(id, safe="") if isinstance(id, str) else None
            try:
                hits.append(_candidate("wellcome", service + "/full/full/0/default.jpg",
                    thumbnail=service + "/full/" + thumb_size + "/0/default.jpg", title=source.get("title"),
                    page=page, license=license.get("url") or license.get("label"), creator=_strings(creators)))
            except EngineError:
                continue
            break
        if len(hits) >= n:
            break
    return hits


def flickr(query, n):
    key = os.environ.get("BADSHOP_FLICKR_API_KEY")
    if not key:
        raise EngineError("Flickr Commons needs BADSHOP_FLICKR_API_KEY in the core's environment")
    try:
        data = _json("https://api.flickr.com/services/rest/", {
            "method": "flickr.photos.search", "api_key": key, "format": "json", "nojsoncallback": 1,
            "text": query, "is_commons": "true", "per_page": n, "sort": "relevance",
            "extras": "url_m,url_l,url_o,owner_name,license"})
        if data.get("stat") == "fail":
            raise ValueError("Flickr rejected the request")
    except Exception:
        # Flickr puts the API key in the query: never persist exception URLs in step results.
        raise EngineError("Flickr Commons request failed; check its API key and connection") from None
    return [_candidate("flickr", item.get("url_l") or item.get("url_o") or item["url_m"],
                thumbnail=item.get("url_m"), title=item.get("title"),
                page="https://www.flickr.com/photos/" + urllib.parse.quote(str(item["owner"]), safe="")
                     + "/" + urllib.parse.quote(str(item["id"]), safe=""),
                license="No known copyright restrictions" if str(item.get("license")) == "7" else None,
                creator=item.get("ownername"))
            for item in data.get("photos", {}).get("photo", [])[:n]
            if item.get("url_m") and item.get("owner") and item.get("id")]


def nasa(query, n):
    data = _json("https://images-api.nasa.gov/search", {"q": query, "media_type": "image", "page_size": n})
    hits = []
    for item in data.get("collection", {}).get("items", [])[:n]:
        detail = (item.get("data") or [{}])[0]
        preview = next((link.get("href") for link in item.get("links", []) if link.get("rel") == "preview"), None)
        nasa_id = detail.get("nasa_id")
        if preview and nasa_id:
            # The preview is already a usable image. acquire resolves the asset manifest on selection.
            hits.append(_candidate("nasa", preview, title=detail.get("title"),
                page="https://images.nasa.gov/details/" + urllib.parse.quote(str(nasa_id), safe=""),
                creator=detail.get("photographer") or detail.get("center")))
    return hits


def web(query, n):
    """Opt-in user-operated JSON search gateway; no credentials go in session tool parameters."""
    endpoint = os.environ.get("BADSHOP_IMAGE_SEARCH_URL")
    if not endpoint:
        raise EngineError("Web search needs BADSHOP_IMAGE_SEARCH_URL in the core's environment")
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EngineError("BADSHOP_IMAGE_SEARCH_URL must be an HTTPS endpoint without credentials or query parameters")
    try:
        data = _json(endpoint, {"q": query, "limit": n})
    except Exception:
        raise EngineError("The configured image-search gateway failed") from None
    return [_candidate("web", item["url"], thumbnail=item.get("thumbnail"), title=item.get("title"),
                       page=item.get("page"), license=item.get("license"), creator=item.get("creator"))
            for item in data.get("results", [])[:n] if item.get("url")]


def _key_request(kind, endpoint, params, key_env, key_param):
    key = os.environ.get(key_env)
    if not key:
        raise EngineError(f"{kind} needs {key_env} in the core's environment")
    try:
        return _json(endpoint, {**params, key_param: key})
    except Exception:
        # These services put credentials in query parameters. Never persist their exception URLs.
        raise EngineError(f"{kind} request failed; check its API key and connection") from None


def smithsonian(query, n):
    data = _key_request("Smithsonian", "https://api.si.edu/openaccess/api/v1.0/search",
                        {"q": f"({query}) AND media_usage:CC0", "rows": min(30, n * 2)},
                        "BADSHOP_SMITHSONIAN_API_KEY", "api_key")
    if data.get("status") != 200:
        raise EngineError("Smithsonian rejected the request; check its API key")
    hits = []
    for row in data.get("response", {}).get("rows", []):
        content = row.get("content", {})
        detail = content.get("descriptiveNonRepeating", {})
        creators = [entry.get("content") for entry in content.get("freetext", {}).get("name", [])
                    if any(role in entry.get("label", "").lower() for role in ("artist", "maker", "author", "photographer"))]
        for media in detail.get("online_media", {}).get("media", []):
            if media.get("type") != "Images" or media.get("usage", {}).get("access") != "CC0":
                continue
            resources = media.get("resources", [])
            original = next((r.get("url") for r in resources if r.get("label") == "High-resolution JPEG"), media.get("content"))
            thumb = next((r.get("url") for r in resources if r.get("label") == "Thumbnail Image"), media.get("thumbnail"))
            if original:
                hits.append(_candidate("smithsonian", original, thumbnail=thumb,
                    title=row.get("title"), page=detail.get("guid"), license="CC0 1.0", creator=_strings(creators)))
            if len(hits) >= n:
                return hits
    return hits


def europeana(query, n):
    data = _key_request("Europeana", "https://api.europeana.eu/record/v2/search.json",
                        {"query": query, "qf": "TYPE:IMAGE", "media": "true", "thumbnail": "true",
                         "reusability": "open", "profile": "rich", "rows": n},
                        "BADSHOP_EUROPEANA_API_KEY", "wskey")
    if data.get("success") is not True:
        raise EngineError("Europeana rejected the request; check its API key")
    def first(value):
        return next((v for v in value if isinstance(v, str) and v), None) if isinstance(value, list) else value
    hits = []
    for item in data.get("items", [])[:n]:
        url = first(item.get("edmIsShownBy"))
        if not url:
            continue  # previews alone are not the original image
        hits.append(_candidate("europeana", url, thumbnail=first(item.get("edmPreview")),
            title=_strings(item.get("title")), page=first(item.get("edmIsShownAt")) or item.get("guid"),
            license=_strings(item.get("rights")), creator=_strings(item.get("dcCreator"))))
    return hits


def bhl(query, n):
    endpoint = "https://www.biodiversitylibrary.org/api3"
    def request(params):
        data = _key_request("Biodiversity Heritage Library", endpoint, {"format": "json", **params},
                            "BADSHOP_BHL_API_KEY", "apikey")
        if data.get("Status") != "ok":
            raise EngineError("Biodiversity Heritage Library rejected the request; check its API key")
        return data.get("Result", [])
    publications = request({"op": "PublicationSearch", "searchterm": query, "searchtype": "C",
                            "page": 1, "pageSize": 4})
    def illustrations(publication):
        kind = publication.get("BHLType")
        identifier = publication.get("ItemID") if kind == "Item" else publication.get("PartID")
        if kind not in ("Item", "Part") or not str(identifier).isdigit():
            return []
        try:
            records = request({"op": "GetItemMetadata" if kind == "Item" else "GetPartMetadata",
                               "id": identifier, "pages": "t", "ocr": "f"})
        except EngineError:
            return []  # a missing volume does not discard the other publications
        hits = []
        for record in records:
            rights = record.get("LicenseUrl") or record.get("LicenseName") or record.get("CopyrightStatus") or record.get("RightsStatus") or record.get("Rights") or record.get("RightsStatement")
            creators = [a.get("Name") for a in publication.get("Authors", [])]
            for page in record.get("Pages", []):
                types = {p.get("PageTypeName", "").strip() for p in page.get("PageTypes", [])}
                if not types.intersection({"Illustration", "Map", "Foldout"}) or not page.get("FullSizeImageUrl"):
                    continue
                number = "; ".join(" ".join(str(v) for v in [p.get("Prefix"), p.get("Number")] if v is not None) for p in page.get("PageNumbers", []))
                title = f"{publication.get('Title', 'BHL illustration')} — {number or 'page ' + str(page.get('PageID', ''))}"
                hits.append(_candidate("bhl", page["FullSizeImageUrl"], thumbnail=page.get("ThumbnailUrl"),
                    title=title, page=page.get("PageUrl"), license=rights, creator=_strings(creators)))
                if len(hits) >= n:
                    return hits
        return hits
    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(illustrations, publications[:4]))
    # Interleave books instead of filling every result with pages from the first one.
    return [group[i] for i in range(n) for group in groups if len(group) > i][:n]


SEARCHERS = {"commons": commons, "openverse": openverse, "loc": loc, "met": met,
             "flickr": flickr, "nasa": nasa, "web": web,
             "smithsonian": smithsonian, "bhl": bhl, "europeana": europeana,
             "cleveland": cleveland, "wellcome": wellcome}


def fingerprint(image):
    """Difference hash plus coarse color: resized/recompressed copies still compare as duplicates."""
    rgb = np.asarray(image.convert("RGB").resize((9, 8), Image.Resampling.BILINEAR), dtype=np.float32)
    grey = rgb.mean(axis=2)
    bits = grey[:, 1:] > grey[:, :-1]
    code = sum(int(bit) << i for i, bit in enumerate(bits.flatten()))
    return code, rgb.mean(axis=(0, 1))


def distance(a, b):
    return (a[0] ^ b[0]).bit_count() / 64 + float(np.linalg.norm(a[1] - b[1])) / 442


def _preview(hit):
    try:
        raw, _ = sources.http_get(hit["thumbnail"], timeout=8, max_bytes=4 * 2**20)
        # Several previews decode concurrently: apply a smaller pixel budget than originals.
        image = sources.load_image(raw, formats=sources.WEB_FORMATS, max_pixels=4_000_000)
        width, height = image.size
        image = ImageOps.contain(image, (300, 300))
        encoded = io.BytesIO()
        image.convert("RGB").save(encoded, "JPEG", quality=75)
        return ({**hit, "width": width, "height": height,
                 "thumbnail_data_url": "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode()},
                image, fingerprint(image))
    except Exception:
        return None


def _rank(hit, image, p):
    text = hit["title"].lower()
    terms = set(re.findall(r"\w+", " ".join(filter(None, [p.query, p.pose, p.expression])).lower()))
    overlap = len(terms & set(re.findall(r"\w+", text))) / max(1, len(terms))
    score, reasons = overlap * 3, []
    if overlap:
        reasons.append("matching description")
    ratio = image.width / image.height
    if p.purpose == "head" and 0.55 <= ratio <= 1.25:
        score += 0.5
        reasons.append("portrait-friendly frame")
    if p.purpose == "head":
        # Bundled Haar data needs no model download; it estimates usable face area, not identity.
        import cv2
        grey = np.asarray(image.convert("L"))
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not detector.empty():
            boxes = detector.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=4, minSize=(25, 25))
            if len(boxes):
                area = max(int(w) * int(h) for _, _, w, h in boxes) / (image.width * image.height)
                score += min(1.0, area * 4)
                reasons.append("detected face occupies " + str(round(area * 100)) + "% of frame")
    if p.purpose == "background" and ratio >= 1.25:
        score += 0.7
        reasons.append("wide frame")
    if min(hit["width"], hit["height"]) >= 200:
        score += 0.3
        reasons.append("usable preview size")
    # Blank margins are useful for captions, but never assert semantic subject/pose detection.
    edges = np.asarray(image.convert("L").filter(ImageFilter.FIND_EDGES))
    top = edges[1:max(2, image.height // 5), 1:-1]
    if top.size and float(top.mean()) < 20:
        score += 0.2
        reasons.append("quiet upper margin")
    return score, reasons


def discover(p: DiscoverParams, reference=None) -> EngineResult:
    query = " ".join(filter(None, [p.query, p.pose, p.expression]))
    names = [item["id"] for item in source_status() if item["configured"]] if p.source == "all" else [p.source]
    per_source = min(12, max(4, (p.n * 3 + len(names) - 1) // len(names)))
    notes = []
    def search(name):
        try:
            fn = subject_commons if name == "commons" and p.same_subject else SEARCHERS[name]
            return name, fn(p.query if fn is subject_commons else query, per_source), None
        except Exception as error:
            # No request URL is returned: configured sources might have secret query parameters.
            reason = error.message if isinstance(error, EngineError) else "source unavailable"
            return name, [], f"{name}: {sources._clean(reason)[:300]}"
    with ThreadPoolExecutor(max_workers=7) as pool:
        groups = list(pool.map(search, names))
    hits, seen = [], set(p.exclude_urls)
    for _, _, error in groups:
        if error:
            notes.append(error)
    # Round robin before the bounded preview fetch preserves source diversity.
    for i in range(per_source):
        for _, group, _ in groups:
            if i < len(group) and group[i]["url"] not in seen:
                hits.append(group[i])
                seen.add(group[i]["url"])
    with ThreadPoolExecutor(max_workers=6) as pool:
        previews = [item for item in pool.map(_preview, hits[:36]) if item]
    if not previews:
        raise EngineError("no usable image previews found", hint="; ".join(notes + ["try fewer words or another source"]))
    ranked = []
    ref = fingerprint(reference) if reference else None
    if ref is None and p.reference_url:
        preview = _preview(_candidate("reference", p.reference_url))
        if preview:
            ref = preview[2]
        else:
            notes.append("reference preview unavailable; ranked by description and framing")
    for hit, image, fp in previews:
        score, reasons = _rank(hit, image, p)
        if ref and p.variation != "balanced":
            separation = distance(fp, ref)
            score += (1.5 - separation if p.variation == "similar" else separation)
            reasons.append("visual similarity" if p.variation == "similar" else "visual variety")
        ranked.append((score, hit, image, fp, reasons))
    selected = []
    duplicates = 0
    while ranked and len(selected) < p.n:
        # Prefer different framing/source after relevance; tie order is stable and repeatable.
        def adjusted(row):
            if not selected:
                return row[0]
            novelty = min(distance(row[3], other[3]) for other in selected)
            source_seen = any(row[1]["source"]["kind"] == other[1]["source"]["kind"] for other in selected)
            return row[0] + novelty * 0.5 - (0.2 if source_seen else 0)
        best = max(range(len(ranked)), key=lambda i: adjusted(ranked[i]))
        row = ranked.pop(best)
        if any(distance(row[3], other[3]) < 0.12 for other in selected):
            duplicates += 1
            continue
        selected.append(row)
    candidates, panels = [], []
    for index, (score, hit, image, _, reasons) in enumerate(selected, 1):
        candidates.append({**hit, "number": index, "score": round(score, 3), "reasons": reasons})
        panels.append((index, image, hit["title"]))
    sheet = sources.contact_sheet(panels)
    return EngineResult(outputs=[Output("sheet", sheet, "discovery_sheet.png")],
        lines=[f"{len(candidates)} candidates; only this contact sheet was imported.",
               "Choose a candidate with acquire(url=..., source_kind=..., page=..., title=..., license=..., creator=...).",
               "Ranking uses description, framing, and visual similarity; inspect the actual pose and expression.", *notes],
        data={"sources": [None], "query": query, "candidates": candidates,
              "duplicates_removed": duplicates, "warnings": notes})


@sources._scrubbed
def acquire(p: AcquireParams) -> EngineResult:
    url = sources._web_url(p.url)
    page = sources._web_url(p.page) if p.page else None
    if p.source_kind == "nasa" and page and page.startswith("https://images.nasa.gov/details/"):
        nasa_id = urllib.parse.unquote(page.rsplit("/", 1)[-1])
        try:
            manifest = _json("https://images-api.nasa.gov/asset/" + urllib.parse.quote(nasa_id, safe=""))
            variants = [item.get("href", "") for item in manifest.get("collection", {}).get("items", [])]
            url = next((item for item in variants if item.lower().endswith("~orig.jpg")),
                       next((item for item in variants if item.lower().endswith(".jpg")), url))
        except (EngineError, OSError, ValueError, TypeError):
            pass  # the inspected preview remains a usable fallback
    try:
        result = sources.fetch_url(url)
    except EngineError:
        if p.source_kind != "nasa" or url == p.url:
            raise
        result = sources.fetch_url(p.url)
        result.lines.append("The NASA original was unavailable; imported the inspected preview.")
    existing = result.data["sources"][0]
    result.data["sources"][0] = sources.provenance(p.source_kind, existing["url"],
        page=page or existing.get("page"), title=p.title, license=p.license, creator=p.creator)
    return result
