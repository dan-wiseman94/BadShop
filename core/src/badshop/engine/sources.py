"""Image sources: Commons + Openverse search, Wikipedia lead images, Twemoji, Imgflip templates, the
clipboard, and plain image or page URLs. Ported from reference/badshop.py."""

import difflib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar, Literal

from PIL import Image, ImageDraw, ImageOps
from pydantic import Field

from badshop.engine.assets import http_get  # always called as a module global, so tests can swap it
from badshop.engine.common import WEB_FORMATS, font, has_alpha, load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Params

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
IMGFLIP_API = "https://api.imgflip.com/get_memes"
TWEMOJI_URL = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{}.png"
IMAGE_MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}
NET_ERRORS = (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException)
NET_HINT = "check the internet connection, or use a local file"


class FetchParams(Params):
    POSITIONAL: ClassVar = ("query",)
    FLAGS: ClassVar = {"n": "-n"}
    query: str | None = Field(None, description='search words like "labrador retriever sitting", or an image or web page URL')
    source: Literal["all", "commons", "openverse"] = Field("all", description="where to search (all interleaves Commons and Openverse)")
    n: int = Field(6, ge=1, le=12, description="how many candidates to download")
    clipboard: bool = Field(False, description="use the image (or image link) on the clipboard")


class WikiParams(Params):
    POSITIONAL: ClassVar = ("title",)
    FLAGS: ClassVar = {"n": "-n"}
    title: str = Field(description='a person, place or thing, e.g. "Abraham Lincoln"')
    n: int = Field(4, ge=1, le=8, description="how many matching articles (the first is usually the exact one)")
    lang: str = Field("en", pattern=r"^[a-z-]{2,12}$", description="Wikipedia language code")


class EmojiParams(Params):
    POSITIONAL: ClassVar = ("emoji",)
    emoji: list[str] = Field(min_length=1, description="emoji characters, hex codes (1f480) or names (skull, joy, fire...)")
    size: int | None = Field(None, ge=8, le=1024, description="nearest-neighbor upscale to this many px")


class TemplateParams(Params):
    POSITIONAL: ClassVar = ("name",)
    FLAGS: ClassVar = {"n": "-n", "list_all": "--list"}
    name: str | None = Field(None, description='template name, e.g. "drake", "distracted boyfriend"')
    n: int = Field(3, ge=1, le=8, description="how many best matches to download")
    list_all: bool = Field(False, description="list every template name instead")


def _hint(reasons: list[str], advice: str) -> str:
    """Keep the collected failure lines in an error's hint, so the reason survives."""
    return "; ".join([*reasons, advice])


def _web_url(url: str) -> str:
    """`url` if it is an http(s) link; anything else (file:, ftp:, data:) is a clean EngineError."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise EngineError("only http and https links can be fetched", hint="copy the image's web address")
    return url


def _keep(im: Image.Image) -> Image.Image:
    """Keep transparency (emoji, stickers, logos); flatten everything else to RGB."""
    return im.convert("RGBA") if has_alpha(im) else im.convert("RGB")


def commons_search(query, n):
    """Top-n bitmap files on Wikimedia Commons for a search, in relevance order."""
    params = {
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": n * 2,  # over-fetch; some hits are odd formats
        "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 1200,
    }
    data, _ = http_get(COMMONS_API + "?" + urllib.parse.urlencode(params))
    pages = json.loads(data).get("query", {}).get("pages", {})
    hits = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in IMAGE_MIMES:
            continue
        hits.append({
            "title": page.get("title", "").removeprefix("File:"),
            "url": info.get("thumburl") or info.get("url"),
            "note": "commons",
        })
    return hits[:n]


def openverse_search(query, n):
    """Top-n openly licensed images from Openverse (Flickr, museums, Commons and more)."""
    params = {"q": query, "page_size": min(20, n * 2), "mature": "false"}
    data, _ = http_get(OPENVERSE_API + "?" + urllib.parse.urlencode(params))
    hits = []
    for r in json.loads(data).get("results", []):
        if not r.get("url"):
            continue
        lic = f"{r.get('license', '?').upper()} {r.get('license_version') or ''}".strip()
        hits.append({
            "title": r.get("title") or "untitled",
            "url": r["url"], "fallback": r.get("thumbnail"),
            "note": f"openverse, {lic}, by {r.get('creator') or 'unknown'}",
        })
    return hits[:n]


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30] or "fetch"


def try_image(data):
    """Downloaded or pasted bytes as an upright image, or None. Only the web formats are decoded,
    so a server can never pick Pillow's riskier decoders (EPS runs Ghostscript)."""
    try:
        return load_image(data, formats=WEB_FORMATS)  # rotates in place, so .format survives
    except Exception:
        return None


def contact_sheet(panels, cols=4, cell=300):
    """Numbered panels so one look is enough to choose a candidate. panels: [(number, image, title)]."""
    rows = (len(panels) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 24)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    big, small = font(28), font(13)
    for i, (num, im, text) in enumerate(panels):
        im = im.convert("RGBA")
        flat = Image.new("RGBA", im.size, (200, 200, 200, 255))  # show transparent bits as grey
        im = ImageOps.contain(Image.alpha_composite(flat, im).convert("RGB"), (cell - 8, cell - 8))
        x0, y0 = (i % cols) * cell, (i // cols) * (cell + 24)
        sheet.paste(im, (x0 + 4, y0 + 4))
        d.rectangle([x0 + 4, y0 + 4, x0 + 44, y0 + 40], fill=(255, 0, 255))
        d.text((x0 + 12, y0 + 6), str(num), font=big, fill="white")
        d.text((x0 + 6, y0 + cell + 4), text[:44], font=small, fill=(220, 220, 220))
    return sheet


def download_candidates(hits, slug, source_line=None) -> EngineResult:
    """Download each hit as a numbered output, plus a contact sheet when there's a choice."""
    # reference/badshop.py download_candidates
    outputs, lines, panels = [], [], []
    for i, h in enumerate(hits, 1):
        im = None
        for url in (h["url"], h.get("fallback")):
            if not url:
                continue
            try:
                im = try_image(http_get(_web_url(url))[0])
            except Exception as e:
                lines.append(f"{i}: {url[:60]} failed ({e})")
            if im is not None:
                break
        if im is None:
            lines.append(f"{i}: skipped, no usable image")
            continue
        fmt = im.format if im.format in FORMAT_EXT else "PNG"  # read before convert() drops .format
        panels.append((i, im, h["title"]))
        note = f"  [{h['note']}]" if h.get("note") else ""
        outputs.append(Output(str(i), _keep(im), f"fetch/{slug}_{i}{FORMAT_EXT[fmt]}", fmt=fmt,
                              caption=f"({im.width}x{im.height}) {h['title']}{note}"))
    if not panels:
        raise EngineError("every candidate failed to download", hint=_hint(lines, "try other words or another source"))
    if len(panels) > 1:
        outputs.append(Output("sheet", contact_sheet(panels), f"fetch/{slug}_sheet.png"))
    if source_line:
        lines.append(source_line)
    return EngineResult(outputs=outputs, lines=lines)


class _PageImage(HTMLParser):
    """Collects the preview image a web page advertises for link unfurls."""
    KEYS = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src")

    def __init__(self):
        super().__init__()
        self.found = {}

    def handle_starttag(self, tag, attrs):
        d = {k: v for k, v in attrs if v}
        if tag == "meta":
            key = (d.get("property") or d.get("name") or "").lower()
            if key in self.KEYS and d.get("content"):
                self.found.setdefault(key, d["content"])
        elif tag == "link" and d.get("rel", "").lower() == "image_src" and d.get("href"):
            self.found.setdefault("image_src", d["href"])


def page_image(html, base):
    p = _PageImage()
    try:
        p.feed(html)
    except Exception:
        pass
    for key in (*_PageImage.KEYS, "image_src"):
        if key in p.found:
            try:
                url = urllib.parse.urljoin(base, p.found[key])
                if urllib.parse.urlsplit(url).scheme in ("http", "https"):  # never a local file: link
                    return url
            except ValueError:  # a malformed link, e.g. an unclosed IPv6 bracket: try the next key
                pass
    return None


def fetch_url(url, follow=True) -> EngineResult:
    # reference/badshop.py fetch_url
    _web_url(url)
    try:
        data, ctype = http_get(url)
    except urllib.error.HTTPError as e:
        raise EngineError(f"{url} returned HTTP {e.code}") from None
    except NET_ERRORS as e:
        raise EngineError(f"couldn't download {url} ({e})", hint=NET_HINT) from None
    im = try_image(data)
    if im is None:
        if follow and ("html" in ctype or data.lstrip()[:1] == b"<"):
            found = page_image(data.decode("utf-8", "replace"), url)
            if found:
                r = fetch_url(found, follow=False)
                r.lines.insert(0, f"page image: {found}")
                return r
            raise EngineError("that page doesn't advertise a preview image (no og:image)",
                              hint="right-click the picture and copy the image address instead")
        raise EngineError(f"that URL returned {ctype or 'something'} that isn't an image")
    name = "fetch/" + slugify(Path(urllib.parse.urlparse(url).path).stem) + ".png"
    return EngineResult(outputs=[Output("fetched", _keep(im), name)], lines=[f"size: {im.width}x{im.height}"])


CLIPBOARD_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")  # what try_image decodes


def _image_type(types: list[str]) -> str | None:
    """The clipboard type to read: a web image format when one is offered, else the first image/*."""
    return next((t for t in CLIPBOARD_IMAGE_TYPES if t in types),
                next((t for t in types if t.startswith("image/")), None))


def read_clipboard():
    """(image bytes, text) from the system clipboard; either may be None."""
    def run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, timeout=10).stdout
        except Exception:
            return b""

    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        types = run(["wl-paste", "--list-types"]).decode(errors="replace").split()
        img = _image_type(types)
        if img:
            return run(["wl-paste", "--no-newline", "--type", img]), None
        return None, run(["wl-paste", "--no-newline"]).decode(errors="replace")
    if shutil.which("xclip"):
        targets = run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]).decode(errors="replace").split()
        img = _image_type(targets)
        if img:
            return run(["xclip", "-selection", "clipboard", "-t", img, "-o"]), None
        return None, run(["xclip", "-selection", "clipboard", "-o"]).decode(errors="replace")
    if sys.platform == "darwin" and shutil.which("pngpaste"):
        return run(["pngpaste", "-"]) or None, None
    raise EngineError("no clipboard tool found", hint="install wl-clipboard (Wayland), xclip (X11), or pngpaste (macOS)")


def fetch_clipboard() -> EngineResult:
    # reference/badshop.py fetch_clipboard
    data, text = read_clipboard()
    if data:
        im = try_image(data)
        if im is None:
            raise EngineError("the clipboard has image data that couldn't be decoded")
        out = Output("fetched", _keep(im), f"fetch/clipboard_{time.strftime('%H%M%S')}.png")
        return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}"])
    text = (text or "").strip()
    if re.match(r"https?://\S+$", text):
        r = fetch_url(text)
        r.lines.insert(0, f"clipboard holds a link: {text}")
        return r
    raise EngineError("the clipboard has no image or link", hint="copy an image (or its address) and try again")


def fetch(p: FetchParams) -> EngineResult:
    # reference/badshop.py cmd_fetch
    if p.clipboard:
        return fetch_clipboard()
    if not p.query:
        raise EngineError("give search words, an image or page URL, or clipboard")
    if re.match(r"https?://", p.query):
        return fetch_url(p.query)

    searches = {"commons": commons_search, "openverse": openverse_search}
    names = list(searches) if p.source == "all" else [p.source]
    lists, failures = [], []
    for name in names:
        try:
            lists.append(searches[name](p.query, p.n))
        except Exception as e:
            failures.append(f"{name} search failed ({e})")
    notes = [f"note: {f}" for f in failures]
    if not lists:
        raise EngineError("; ".join(failures), hint=NET_HINT)
    hits, seen = [], set()
    for group in zip(*[l + [None] * (p.n - len(l)) for l in lists]):  # interleave the sources
        for h in group:
            if h and h["url"] not in seen:
                seen.add(h["url"])
                hits.append(h)
    if not hits:
        raise EngineError(f"no images found for {p.query!r}",
                          hint=_hint(notes, "try other words, `wiki`, or ask the user for a file or URL"))
    r = download_candidates(hits[:p.n], slugify(p.query),
                            "source: commons = Wikimedia Commons (free licenses); openverse = license shown per image")
    r.lines[:0] = notes
    return r


def wiki(p: WikiParams) -> EngineResult:
    # reference/badshop.py cmd_wiki
    api = f"https://{p.lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": p.title,
        "gsrnamespace": 0, "gsrlimit": p.n * 3, "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": 1200, "pilimit": "max",
    }
    try:
        data, _ = http_get(api + "?" + urllib.parse.urlencode(params))
        pages = sorted(json.loads(data).get("query", {}).get("pages", {}).values(), key=lambda q: q.get("index", 0))
        hits = [{"title": q["title"], "url": q["thumbnail"]["source"], "note": "wikipedia lead image"}
                for q in pages if q.get("thumbnail")][:p.n]
    except Exception as e:
        raise EngineError(f"Wikipedia search failed ({e})", hint=NET_HINT) from None
    if not hits:
        raise EngineError(f"no Wikipedia article with an image matched {p.title!r}", hint="try `fetch` instead")
    return download_candidates(hits, "wiki_" + slugify(p.title),
                               f"source: {p.lang}.wikipedia.org lead images (mostly from Wikimedia Commons)")


EMOJI_NAMES = {
    "joy": "😂", "rofl": "🤣", "laughing": "😆", "sob": "😭", "skull": "💀", "fire": "🔥",
    "100": "💯", "eyes": "👀", "ok": "👌", "b": "🅱️", "sunglasses": "😎", "clown": "🤡",
    "moyai": "🗿", "thinking": "🤔", "pray": "🙏", "heart_eyes": "😍", "cap": "🧢", "goat": "🐐",
    "stonks": "📈", "flag_us": "🇺🇸", "eagle": "🦅", "crown": "👑", "money": "💰", "flex": "💪",
    "nerd": "🤓", "cold": "🥶", "hot": "🥵", "pleading": "🥺", "salute": "🫡", "exploding": "🤯",
}


def emoji_code(s) -> str:
    """Twemoji file name for an emoji: hex codepoints joined by '-', FE0F dropped unless it's a ZWJ sequence."""
    s = EMOJI_NAMES.get(s.lower().strip(":"), s)
    if re.fullmatch(r"[0-9a-fA-F]{4,6}(-[0-9a-fA-F]{4,6})*", s):
        return s.lower()
    cps = [ord(c) for c in s]
    if 0x200D not in cps:
        cps = [c for c in cps if c != 0xFE0F]
    return "-".join(f"{c:x}" for c in cps)


def emoji(p: EmojiParams) -> EngineResult:
    # reference/badshop.py cmd_emoji
    suggestion = "try the emoji character itself, or one of: " + ", ".join(sorted(EMOJI_NAMES))
    outputs, lines, missing = [], [], []
    for e in p.emoji:
        code = emoji_code(e)
        url = TWEMOJI_URL.format(code)
        try:
            im = try_image(http_get(url)[0])
        except urllib.error.HTTPError:
            im = None
        except NET_ERRORS as err:
            raise EngineError(f"couldn't download {url} ({err})", hint=NET_HINT) from None
        if im is None:
            missing.append(f"{e}: no Twemoji image for {code}")
            lines.append(f"{missing[-1]}; {suggestion}")
            continue
        if p.size:
            im = im.convert("RGBA").resize((p.size, p.size), Image.NEAREST)
        outputs.append(Output("emoji", _keep(im), f"fetch/emoji_{code}.png",
                              caption=f"({im.width}x{im.height}) {EMOJI_NAMES.get(e.lower().strip(':'), e)}"))
    if not outputs:
        raise EngineError("no emoji downloaded", hint=_hint(missing, suggestion))
    lines.append("source: Twemoji (CC-BY 4.0), transparent PNGs; paste scales them with hard pixels")
    return EngineResult(outputs=outputs, lines=lines)


def template(p: TemplateParams) -> EngineResult:
    # reference/badshop.py cmd_template
    try:
        memes = json.loads(http_get(IMGFLIP_API)[0])["data"]["memes"]
    except Exception as e:
        raise EngineError(f"Imgflip template list failed ({e})", hint=NET_HINT) from None
    if p.list_all or not p.name:
        return EngineResult(lines=[f"{m['name']}  ({m['width']}x{m['height']}, {m['box_count']} text boxes)"
                                   for m in memes])
    q = p.name.lower()

    def score(m):
        name = m["name"].lower()
        words = set(re.findall(r"\w+", q))
        overlap = len(words & set(re.findall(r"\w+", name))) / max(1, len(words))
        return (q in name) * 2 + overlap + difflib.SequenceMatcher(None, q, name).ratio()

    best = sorted(memes, key=score, reverse=True)[:p.n]
    hits = [{"title": m["name"], "url": m["url"], "note": f"{m['box_count']} text boxes"} for m in best]
    return download_candidates(hits, "template_" + slugify(p.name), "source: imgflip.com top-100 meme templates")
