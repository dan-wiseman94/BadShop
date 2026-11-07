"""Selected-item importers. No archive scraping or bulk collection downloads."""

import re
import urllib.parse
from typing import Literal
from pydantic import Field
from badshop.engine import discovery, sources
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params


def chicago(query, n):
    data = discovery._json(
        "https://api.artic.edu/api/v1/artworks/search",
        {
            "q": query,
            "limit": n,
            "fields": "id,title,image_id,artist_display,is_public_domain",
            "query[term][is_public_domain]": "true",
        },
    )
    root = data.get("config", {}).get("iiif_url", "https://www.artic.edu/iiif/2")
    return [
        discovery._candidate(
            "chicago",
            f"{root}/{r['image_id']}/full/843,/0/default.jpg",
            thumbnail=f"{root}/{r['image_id']}/full/200,/0/default.jpg",
            title=r.get("title"),
            page=f"https://www.artic.edu/artworks/{r['id']}",
            license="CC0 / public domain",
            creator=r.get("artist_display"),
        )
        for r in data.get("data", [])
        if r.get("image_id") and r.get("is_public_domain")
    ][:n]


def openmoji(query, n):
    # Pin the release; source bytes/credits are copied into the project on acquisition.
    root = "https://raw.githubusercontent.com/hfg-gmuend/openmoji/16.0.0"
    rows = discovery._json(root + "/data/openmoji.json")
    terms = query.lower().split()
    hits = [
        r
        for r in rows
        if all(t in (str(r.get("annotation", "")) + " " + str(r.get("tags", ""))).lower() for t in terms)
    ]
    return [
        discovery._candidate(
            "openmoji",
            root + "/color/618x618/" + r["hexcode"] + ".png",
            title=r.get("annotation"),
            page="https://openmoji.org/library/emoji-" + r["hexcode"] + "/",
            license="CC BY-SA 4.0",
            creator=r.get('openmoji_author') or "OpenMoji contributors",
        )
        for r in hits[:n]
    ]


class CollectionParams(Params):
    kind: Literal["iiif", "archive", "lospec"]
    identifier: str = Field(
        min_length=1,
        max_length=4096,
        description="IIIF manifest URL, Internet Archive item identifier, or Lospec palette slug",
    )
    offset: int = Field(0, ge=0, le=10000)
    limit: int = Field(12, ge=1, le=24)


def label(value):
    if isinstance(value, str):
        return (sources.html_text(value) or '')[:500]
    if isinstance(value, dict):
        return label(next(iter(value.values()), ""))
    if isinstance(value, list):
        return "; ".join(label(v) for v in value)[:500]
    return ""


@sources._scrubbed
def browse(p):
    candidates = []
    if p.kind == "lospec":
        if not re.fullmatch(r"[a-z0-9-]{1,100}", p.identifier):
            raise EngineError("enter a palette slug, for example pico-8")
        data = discovery._json("https://lospec.com/palette-list/" + p.identifier + ".json")
        colors = data.get("colors", [])
        if not 2 <= len(colors) <= 256 or any(
            not isinstance(c, str) or not re.fullmatch("[0-9a-fA-F]{6}", c) for c in colors
        ):
            raise EngineError("the palette returned invalid colors")
        return EngineResult(
            data={
                "colors": ["#" + c for c in colors],
                "name": label(data.get("name")),
                "author": label(data.get("author")),
                "page": "https://lospec.com/palette-list/" + p.identifier,
            },
            lines=["Palette loaded. Apply palette with these explicit colors to preserve it offline."],
        )
    if p.kind == "archive":
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", p.identifier):
            raise EngineError("enter an Internet Archive item identifier")
        data = discovery._json("https://archive.org/metadata/" + p.identifier)
        meta = data.get("metadata", {})
        page = "https://archive.org/details/" + p.identifier
        files = [
            f
            for f in data.get("files", [])
            if str(f.get("name", "")).lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        ]
        for f in files[p.offset : p.offset + p.limit]:
            url = (
                "https://archive.org/download/" + p.identifier + "/" + urllib.parse.quote(f["name"], safe="")
            )
            candidates.append(
                discovery._candidate(
                    "archive",
                    url,
                    title=f["name"],
                    page=page,
                    license=label(meta.get("licenseurl")) or None,
                    creator=label(meta.get("creator")) or None,
                )
            )
        total = len(files)
    else:
        manifest = sources._web_url(p.identifier)
        data = discovery._json(manifest)
        canvases = data.get("items") or next(iter(data.get("sequences", [])), {}).get("canvases", [])
        if not isinstance(canvases, list):
            raise EngineError("not a supported IIIF presentation manifest")
        total = len(canvases)
        for c in canvases[p.offset : p.offset + p.limit]:
            bodies = []
            for page in c.get("items", []):
                for a in page.get("items", []):
                    if a.get("motivation") != "painting":
                        continue
                    body = a.get("body", {})
                    bodies.extend(body if isinstance(body, list) else [body])
            bodies.extend(a.get("resource", {}) for a in c.get("images", []))
            for b in bodies[:4]:
                if b.get("type", b.get("@type")) not in ("Image", "dctypes:Image"):
                    continue
                url = b.get("id", b.get("@id"))
                if not url:
                    continue
                candidates.append(
                    discovery._candidate(
                        "iiif",
                        url,
                        title=label(c.get("label")) or label(data.get("label")),
                        page=manifest,
                        license=label(b.get("rights") or data.get("rights") or data.get("license")) or None,
                        creator=label(
                            data.get("requiredStatement", {}).get("value") or data.get("attribution")
                        )
                        or None,
                    )
                )
    return EngineResult(
        data={
            "candidates": candidates[: p.limit],
            "total": total,
            "offset": p.offset,
            "next_offset": p.offset + p.limit if p.offset + p.limit < total else None,
        },
        lines=[
            f"{len(candidates[: p.limit])} candidates. Select a file to acquire; rights are supplied by the collection and may be unknown."
        ],
    )
