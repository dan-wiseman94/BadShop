#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow>=10.1",
#     "numpy",
#     "opencv-python-headless>=4.8,<5",  # 5.x dropped the Haar cascades that cat detection uses
#     "rembg[cpu]",
# ]
# ///
"""badshop: cut-and-paste tools for deliberately bad, old-internet photoshops.

No generative model touches the pixels. Each command does one dumb thing:

  prep       make a small working copy of an image, plus a gridded copy for picking coordinates
  fetch      search Wikimedia Commons + Openverse, download an image or page URL, or grab the clipboard
  wiki       the lead image of Wikipedia articles (best for named people, places and things)
  emoji      Twemoji PNGs by character or name (😂, joy, skull...)
  template   classic meme templates from Imgflip by name (drake, distracted boyfriend...)
  find       locate faces (or cat faces): head, face-oval, eye, nose, mouth, chin points and tilt
  cutout     crop a box, knock out its background with hard edges; or an oval face; optional sticker outline
  paste      paste a cutout onto another image (nearest-neighbor scaling, no blending)
  text       Impact caption, MS Paint text, or rainbow 3D WordArt
  draw       red circles, arrows, lines and rectangles, MS Paint style
  censor     pixelate, black-bar or blur a rectangle
  eyes       laser eyes
  warp       bulge or pinch spots (giant eyes, huge nose)
  flare      a 2004 lens flare
  sparkle    clip-art sparkles
  watermark  Unregistered HyperCam 2, Bandicam, iFunny, Mematic, or your own
  filter     the "found the Filters menu" effects: emboss, edges, solarize, posterize...
  save       write the result as a crunchy low-quality JPEG (or a dithered GIF)
  deepfry    deep-fried meme treatment: blown-out color and contrast, oversharpened, grainy, JPEG'd to death
  animate    animated GIF: flip between images, shake, flash, zoom, spin
  recipe     turn the command history into a replayable recipe file
  run        replay a recipe, optionally with changed variables
  info       print an image's size

Run any command with -h for its options. Run with `uv run badshop.py ...` and the
dependencies above install themselves on first use.
"""

import argparse
import difflib
import functools
import io
import json
import math
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

try:
    from PIL import (Image, ImageChops, ImageColor, ImageDraw, ImageEnhance, ImageFilter,
                     ImageFont, ImageOps)
except ImportError:
    sys.exit("Pillow is not installed. Run this script with `uv run badshop.py ...` "
             "(it installs its own dependencies), or:  pip install pillow")

WORK_DIR = Path("badshop_work")
FINAL_DIR = Path(os.environ.get("BADSHOP_OUT") or Path.home() / "Pictures" / "badshop")
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "badshop"
HISTORY = WORK_DIR / "history.jsonl"
USER_AGENT = "badshop-skill/1.1 (personal cut-and-paste tool, run locally by its user)"
RECORDING = True  # `run` turns this off so replays don't re-log themselves


# ---------------------------------------------------------------- helpers

def out_path(explicit, default_name):
    """Use the -o path if given, otherwise put the file in ./badshop_work/."""
    p = Path(explicit) if explicit else WORK_DIR / default_name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def final_path(explicit, image, suffix, ext, name=None):
    """Finished memes go to ~/Pictures/badshop/ (or $BADSHOP_OUT) without overwriting older ones."""
    if explicit:
        return out_path(explicit, None)
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    stem = name or re.sub(r"_(work|result)$", "", Path(image).stem) + suffix
    p, i = FINAL_DIR / f"{stem}{ext}", 2
    while p.exists():
        p, i = FINAL_DIR / f"{stem}_{i}{ext}", i + 1
    return p


def open_rgb(path):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)  # phone photos carry their rotation in EXIF
    return im.convert("RGB")


def has_alpha(im):
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # older Pillow has no size argument
        return ImageFont.load_default()


def label(draw, xy, text, fnt):
    x, y = xy
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((x + dx, y + dy), text, font=fnt, fill=(0, 0, 0))
    draw.text((x, y), text, font=fnt, fill=(255, 255, 255))


def draw_grid(im, major=100, minor=50):
    """Magenta gridlines every `minor` px, labeled with pixel coords every `major` px."""
    g = im.copy()
    d = ImageDraw.Draw(g)
    w, h = g.size
    fnt = font(max(11, min(w, h) // 55))
    for x in range(0, w, minor):
        is_major = x % major == 0
        d.line([(x, 0), (x, h)], fill=(255, 0, 255) if is_major else (255, 170, 255), width=1)
        if is_major:
            label(d, (x + 3, 2), str(x), fnt)
    for y in range(0, h, minor):
        is_major = y % major == 0
        d.line([(0, y), (w, y)], fill=(255, 0, 255) if is_major else (255, 170, 255), width=1)
        if is_major:
            label(d, (3, y + 2), str(y), fnt)
    return g


def clamp_box(box, size):
    x1, y1, x2, y2 = box
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    w, h = size
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        sys.exit(f"box {box} is empty or lies outside the {w}x{h} image")
    return x1, y1, x2, y2


def rgb(color):
    try:
        return ImageColor.getrgb(color)[:3]
    except ValueError:
        sys.exit(f"unknown color {color!r}; use a name like red or a hex value like #ff00ff")


def need_cv2():
    try:
        import cv2
        import numpy as np
    except ImportError:
        sys.exit("OpenCV is not installed. Run this script with `uv run badshop.py ...`, or:  "
                 'pip install "opencv-python-headless<5" numpy')
    return cv2, np


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def cached(name, url):
    """Download a model or font once into ~/.cache/badshop/ and reuse it."""
    p = CACHE_DIR / name
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        data, _ = http_get(url, timeout=60)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
    return p


# ------------------------------------------------------------------ fonts

FONT_DIRS = [
    Path("C:/Windows/Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"), Path.home() / "Library/Fonts",
    Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
    Path.home() / ".fonts", Path.home() / ".local/share/fonts", CACHE_DIR / "fonts",
]
FONT_CANDIDATES = {  # first hit wins; the real thing on Windows/macOS, a free lookalike downloaded elsewhere
    "impact": ["impact.ttf", "Impact.ttf", "Anton-Regular.ttf", "LiberationSansNarrow-Bold.ttf",
               "DejaVuSansCondensed-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"],
    "paint": ["comicbd.ttf", "comic.ttf", "Comic Sans MS Bold.ttf", "Comic Sans MS.ttf",
              "ComicNeue-Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"],
    "plain": ["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
    "bold": ["arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
}
FONT_CANDIDATES["wordart"] = FONT_CANDIDATES["impact"]
FONT_DOWNLOADS = {  # SIL Open Font License lookalikes, fetched once when nothing better is installed
    "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "ComicNeue-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/comicneue/ComicNeue-Bold.ttf",
}


@functools.lru_cache(maxsize=None)
def find_font_file(style, explicit=None):
    """Path (or Pillow-searchable name) of the best font for a style, or None for the built-in one."""
    names = [explicit] if explicit else FONT_CANDIDATES[style]
    for name in names:
        if Path(name).is_file():
            return name
        for d in FONT_DIRS:
            if d.is_dir():
                hit = next(d.rglob(name), None)
                if hit:
                    return str(hit)
        try:  # Pillow does its own platform search too
            ImageFont.truetype(name, 10)
            return name
        except OSError:
            pass
        if name in FONT_DOWNLOADS and not explicit:
            try:
                return str(cached(f"fonts/{name}", FONT_DOWNLOADS[name]))
            except Exception:
                pass  # offline: keep going down the list
    return None


def load_font(style, size, explicit=None):
    path = find_font_file(style, explicit)
    if path is None:
        return font(size), "built-in"
    return ImageFont.truetype(path, size), Path(path).name


def wrap_text(draw, text, fnt, max_width):
    lines = []
    for para in text.split("\\n"):
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if not cur or draw.textlength(trial, font=fnt) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return [l for l in lines if l]


def rainbow(size):
    """Left-to-right red-to-violet gradient, the WordArt preset everyone picked."""
    w, h = size
    hue = Image.linear_gradient("L").rotate(90).resize((w, h)).point(lambda v: v * 210 // 255)
    full = Image.new("L", (w, h), 255)
    return Image.merge("HSV", (hue, full, full)).convert("RGBA")


def render_text(lines, fnt, style, color):
    """RGBA layer with the text, tight around it."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    stroke = max(2, fnt.size // 14) if style in ("impact", "wordart") else 0
    shadow = max(2, fnt.size // 12) if style == "paint" else 0
    depth = max(3, fnt.size // 7) if style == "wordart" else 0
    off = shadow + depth
    widths = [probe.textlength(l, font=fnt) for l in lines]
    ascent, descent = fnt.getmetrics()
    lh = ascent + descent
    W = int(max(widths)) + 2 * stroke + off + 4
    H = lh * len(lines) + 2 * stroke + off + 4
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if style == "wordart":
        outer, inner = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
        do, di = ImageDraw.Draw(outer), ImageDraw.Draw(inner)
        for i, line in enumerate(lines):
            x, y = (W - off - widths[i]) / 2, stroke + i * lh
            do.text((x, y), line, font=fnt, fill=255, stroke_width=stroke, stroke_fill=255)
            di.text((x, y), line, font=fnt, fill=255)
        side = Image.new("RGBA", (W, H), rgb(color) + (255,))
        for k in range(depth, 0, -1):  # solid extrusion down and to the right
            layer.paste(side, (0, 0), ImageChops.offset(outer, k, k))
        layer.paste(Image.new("RGBA", (W, H), (0, 0, 0, 255)), (0, 0), outer)
        layer.paste(rainbow((W, H)), (0, 0), inner)
        return layer
    for i, line in enumerate(lines):
        x, y = (W - shadow - widths[i]) / 2, stroke + i * lh
        if style == "impact":
            d.text((x, y), line, font=fnt, fill="white", stroke_width=stroke, stroke_fill="black")
        else:
            d.text((x + shadow, y + shadow), line, font=fnt, fill="black")
            d.text((x, y), line, font=fnt, fill=color)
    return layer


# ----------------------------------------------------------------- fetch

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
IMGFLIP_API = "https://api.imgflip.com/get_memes"
TWEMOJI_URL = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{}.png"
IMAGE_MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}


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
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        return im
    except Exception:
        return None


def save_fetched(im, out):
    """Keep transparency (emoji, stickers, logos); flatten everything else to RGB."""
    (im.convert("RGBA") if has_alpha(im) else im.convert("RGB")).save(out)


def contact_sheet(panels, cols=4, cell=300):
    """Numbered panels so one Read is enough to choose a candidate. panels: [(number, image, title)]."""
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


def download_candidates(hits, slug, source_line=None):
    """Download each hit, print numbered paths, and write a contact sheet when there's a choice."""
    panels = []
    for i, h in enumerate(hits, 1):
        im = None
        for url in (h["url"], h.get("fallback")):
            if not url:
                continue
            try:
                im = try_image(http_get(url)[0])
            except Exception as e:
                print(f"{i}: {url[:60]} failed ({e})")
            if im is not None:
                break
        if im is None:
            print(f"{i}: skipped, no usable image")
            continue
        out = out_path(None, f"fetch/{slug}_{i}{FORMAT_EXT.get(im.format, '.png')}")
        save_fetched(im, out)
        panels.append((i, im, h["title"]))
        note = f"  [{h['note']}]" if h.get("note") else ""
        print(f"{i}: {out} ({im.width}x{im.height}) {h['title']}{note}")
    if not panels:
        sys.exit("every candidate failed to download")
    if len(panels) > 1:
        sheet = out_path(None, f"fetch/{slug}_sheet.png")
        contact_sheet(panels).save(sheet)
        print(f"sheet: {sheet}")
    if source_line:
        print(source_line)


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
            return urllib.parse.urljoin(base, p.found[key])
    return None


def fetch_url(url, out, follow=True):
    try:
        data, ctype = http_get(url)
    except urllib.error.HTTPError as e:
        sys.exit(f"{url} returned HTTP {e.code}")
    im = try_image(data)
    if im is None:
        if follow and ("html" in ctype or data.lstrip()[:1] == b"<"):
            found = page_image(data.decode("utf-8", "replace"), url)
            if found:
                print(f"page image: {found}")
                return fetch_url(found, out, follow=False)
            sys.exit("that page doesn't advertise a preview image (no og:image); "
                     "right-click the picture and copy the image address instead")
        sys.exit(f"that URL returned {ctype or 'something'} that isn't an image")
    out = out_path(out, "fetch/" + slugify(Path(urllib.parse.urlparse(url).path).stem) + ".png")
    save_fetched(im, out)
    print(f"fetched: {out}")
    print(f"size: {im.width}x{im.height}")


def read_clipboard():
    """(image bytes, text) from the system clipboard; either may be None."""
    def run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, timeout=10).stdout
        except Exception:
            return b""

    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        types = run(["wl-paste", "--list-types"]).decode(errors="replace").split()
        img = next((t for t in types if t.startswith("image/")), None)
        if img:
            return run(["wl-paste", "--no-newline", "--type", img]), None
        return None, run(["wl-paste", "--no-newline"]).decode(errors="replace")
    if shutil.which("xclip"):
        targets = run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]).decode(errors="replace").split()
        img = next((t for t in targets if t.startswith("image/")), None)
        if img:
            return run(["xclip", "-selection", "clipboard", "-t", img, "-o"]), None
        return None, run(["xclip", "-selection", "clipboard", "-o"]).decode(errors="replace")
    if sys.platform == "darwin" and shutil.which("pngpaste"):
        return run(["pngpaste", "-"]) or None, None
    sys.exit("no clipboard tool found: install wl-clipboard (Wayland), xclip (X11), or pngpaste (macOS)")


def fetch_clipboard(out):
    data, text = read_clipboard()
    if data:
        im = try_image(data)
        if im is None:
            sys.exit("the clipboard has image data that couldn't be decoded")
        out = out_path(out, f"fetch/clipboard_{time.strftime('%H%M%S')}.png")
        save_fetched(im, out)
        print(f"fetched: {out}")
        print(f"size: {im.width}x{im.height}")
        return
    text = (text or "").strip()
    if re.match(r"https?://\S+$", text):
        print(f"clipboard holds a link: {text}")
        return fetch_url(text, out)
    sys.exit("the clipboard has no image or link; copy an image (or its address) and try again")


def cmd_fetch(a):
    if a.clipboard:
        return fetch_clipboard(a.out)
    if not a.query:
        sys.exit("give search words, an image or page URL, or --clipboard")
    if re.match(r"https?://", a.query):
        return fetch_url(a.query, a.out)

    searches = {"commons": commons_search, "openverse": openverse_search}
    names = list(searches) if a.source == "all" else [a.source]
    lists = []
    for name in names:
        try:
            lists.append(searches[name](a.query, a.n))
        except Exception as e:
            print(f"note: {name} search failed ({e})")
    hits, seen = [], set()
    for group in zip(*[l + [None] * (a.n - len(l)) for l in lists]):  # interleave the sources
        for h in group:
            if h and h["url"] not in seen:
                seen.add(h["url"])
                hits.append(h)
    if not hits:
        sys.exit(f"no images found for {a.query!r}; try other words, `wiki`, or ask the user for a file or URL")
    download_candidates(hits[:a.n], slugify(a.query),
                        "source: commons = Wikimedia Commons (free licenses); openverse = license shown per image")


def cmd_wiki(a):
    api = f"https://{a.lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": a.title,
        "gsrnamespace": 0, "gsrlimit": a.n * 3, "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": 1200, "pilimit": "max",
    }
    try:
        data, _ = http_get(api + "?" + urllib.parse.urlencode(params))
    except Exception as e:
        sys.exit(f"Wikipedia search failed: {e}")
    pages = sorted(json.loads(data).get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    hits = [{"title": p["title"], "url": p["thumbnail"]["source"], "note": "wikipedia lead image"}
            for p in pages if p.get("thumbnail")][:a.n]
    if not hits:
        sys.exit(f"no Wikipedia article with an image matched {a.title!r}; try `fetch` instead")
    download_candidates(hits, "wiki_" + slugify(a.title),
                        f"source: {a.lang}.wikipedia.org lead images (mostly from Wikimedia Commons)")


EMOJI_NAMES = {
    "joy": "😂", "rofl": "🤣", "laughing": "😆", "sob": "😭", "skull": "💀", "fire": "🔥",
    "100": "💯", "eyes": "👀", "ok": "👌", "b": "🅱️", "sunglasses": "😎", "clown": "🤡",
    "moyai": "🗿", "thinking": "🤔", "pray": "🙏", "heart_eyes": "😍", "cap": "🧢", "goat": "🐐",
    "stonks": "📈", "flag_us": "🇺🇸", "eagle": "🦅", "crown": "👑", "money": "💰", "flex": "💪",
    "nerd": "🤓", "cold": "🥶", "hot": "🥵", "pleading": "🥺", "salute": "🫡", "exploding": "🤯",
}


def emoji_code(s):
    """Twemoji file name for an emoji: hex codepoints joined by '-', FE0F dropped unless it's a ZWJ sequence."""
    s = EMOJI_NAMES.get(s.lower().strip(":"), s)
    if re.fullmatch(r"[0-9a-fA-F]{4,6}(-[0-9a-fA-F]{4,6})*", s):
        return s.lower()
    cps = [ord(c) for c in s]
    if 0x200D not in cps:
        cps = [c for c in cps if c != 0xFE0F]
    return "-".join(f"{c:x}" for c in cps)


def cmd_emoji(a):
    got = 0
    for e in a.emoji:
        code = emoji_code(e)
        try:
            im = try_image(http_get(TWEMOJI_URL.format(code))[0])
        except urllib.error.HTTPError:
            im = None
        if im is None:
            print(f"{e}: no Twemoji image for {code}; try the emoji character itself, or one of: "
                  + ", ".join(sorted(EMOJI_NAMES)))
            continue
        if a.size:
            im = im.convert("RGBA").resize((a.size, a.size), Image.NEAREST)
        out = out_path(None, f"fetch/emoji_{code}.png")
        save_fetched(im, out)
        print(f"emoji: {out} ({im.width}x{im.height}) {EMOJI_NAMES.get(e.lower().strip(':'), e)}")
        got += 1
    if not got:
        sys.exit("no emoji downloaded")
    print("source: Twemoji (CC-BY 4.0), transparent PNGs; paste scales them with hard pixels")


def cmd_template(a):
    try:
        memes = json.loads(http_get(IMGFLIP_API)[0])["data"]["memes"]
    except Exception as e:
        sys.exit(f"Imgflip template list failed: {e}")
    if a.list or not a.name:
        for m in memes:
            print(f"{m['name']}  ({m['width']}x{m['height']}, {m['box_count']} text boxes)")
        return
    q = a.name.lower()

    def score(m):
        name = m["name"].lower()
        words = set(re.findall(r"\w+", q))
        overlap = len(words & set(re.findall(r"\w+", name))) / max(1, len(words))
        return (q in name) * 2 + overlap + difflib.SequenceMatcher(None, q, name).ratio()

    best = sorted(memes, key=score, reverse=True)[:a.n]
    hits = [{"title": m["name"], "url": m["url"], "note": f"{m['box_count']} text boxes"} for m in best]
    download_candidates(hits, "template_" + slugify(a.name), "source: imgflip.com top-100 meme templates")


# ------------------------------------------------------------------ find

YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")


def overlap(a, b):
    """Intersection over the smaller box's area."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small else 0


def int_box(box, W, H):
    x1, y1, x2, y2 = box
    return (max(0, round(x1)), max(0, round(y1)), min(W, round(x2)), min(H, round(y2)))


def yunet_faces(cv2, bgr, min_score):
    """Faces with five landmarks each, from OpenCV's small YuNet CNN."""
    model = cached("face_detection_yunet_2023mar.onnx", YUNET_URL)
    H, W = bgr.shape[:2]
    det = cv2.FaceDetectorYN.create(str(model), "", (W, H), min_score, 0.3, 5000)
    _, rows = det.detect(bgr)
    faces = []
    for r in ([] if rows is None else rows.tolist()):
        x, y, w, h = r[:4]
        eyes = sorted([(r[4], r[5]), (r[6], r[7])])  # left to right in the image
        mouth = sorted([(r[10], r[11]), (r[12], r[13])])
        ec = ((eyes[0][0] + eyes[1][0]) / 2, (eyes[0][1] + eyes[1][1]) / 2)
        mc = ((mouth[0][0] + mouth[1][0]) / 2, (mouth[0][1] + mouth[1][1]) / 2)
        em = max(1.0, math.dist(ec, mc))  # eyes-to-mouth distance: the unit for everything below
        ed = max(1.0, math.dist(*eyes))
        ux, uy = (mc[0] - ec[0]) / em, (mc[1] - ec[1]) / em  # down the face, even when it's tilted
        chin = (mc[0] + ux * 0.7 * em, mc[1] + uy * 0.7 * em)
        top, bottom = ec[1] - 2.5 * em, chin[1] + 0.3 * em  # hair above, a strip of neck below
        cx = (ec[0] + chin[0]) / 2
        half = max(0.45 * (bottom - top), 1.6 * ed)
        faces.append({
            "kind": "face", "score": r[14],
            "box": int_box((x, y, x + w, y + h), W, H),
            "head": int_box((cx - half, top, cx + half, bottom), W, H),
            "oval": int_box((cx - 1.15 * ed, ec[1] - 0.75 * em, cx + 1.15 * ed, chin[1]), W, H),
            "eyes": [tuple(round(v) for v in e) for e in eyes], "estimated": False,
            "nose": (round(r[8]), round(r[9])),
            "mouth": [tuple(round(v) for v in m) for m in mouth],
            "chin": (round(chin[0]), round(chin[1])),
            "roll": math.degrees(math.atan2(eyes[1][1] - eyes[0][1], eyes[1][0] - eyes[0][0])),
        })
    return faces


def haar_faces(cv2, gray, kind):
    """Older, rougher cascade detector: the fallback for faces, and the only option for cats."""
    H, W = gray.shape[:2]
    minsize = (max(20, min(W, H) // 20),) * 2

    def detect(name, img, scale=1.1, neighbors=5):
        c = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        return [tuple(int(v) for v in r) for r in c.detectMultiScale(img, scale, neighbors, minSize=minsize)]

    boxes = []
    if kind == "face":
        boxes += detect("haarcascade_frontalface_default.xml", gray)
        boxes += detect("haarcascade_profileface.xml", gray)
        boxes += [(W - x - w, y, w, h) for (x, y, w, h) in detect("haarcascade_profileface.xml", cv2.flip(gray, 1))]
    else:
        boxes += detect("haarcascade_frontalcatface_extended.xml", gray, 1.05, 3)

    eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    faces = []
    for (x, y, w, h) in boxes:
        roi = gray[y:y + int(h * 0.65), x:x + w]
        eyes = eye_cascade.detectMultiScale(roi, 1.1, 5, minSize=(max(8, w // 10),) * 2)
        eyes = sorted(eyes, key=lambda e: -e[2] * e[3])[:2]
        centers = sorted((x + ex + ew // 2, y + ey + eh // 2) for (ex, ey, ew, eh) in eyes)
        estimated = len(centers) != 2
        if estimated:
            centers = [(x + int(w * 0.3), y + int(h * 0.4)), (x + int(w * 0.7), y + int(h * 0.4))]
        faces.append({
            "kind": kind, "score": None, "box": (x, y, x + w, y + h),
            "head": int_box((x - w / 4, y - h * 0.45, x + w * 1.25, y + h * 1.15), W, H),
            "oval": int_box((x + w * 0.12, y + h * 0.1, x + w * 0.88, y + h), W, H),
            "eyes": centers, "estimated": estimated,
        })
    return faces


def cmd_find(a):
    cv2, np = need_cv2()
    im = open_rgb(a.image)
    W, H = im.size
    arr = np.array(im)
    gray = cv2.equalizeHist(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY))

    found = []
    if a.what in ("faces", "all"):
        detector = a.detector
        if detector in ("auto", "yunet"):
            try:
                found += yunet_faces(cv2, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), a.min_score)
            except Exception as e:
                if detector == "yunet":
                    sys.exit(f"YuNet failed: {e}")
                print(f"note: YuNet unavailable ({e}); using Haar cascades, whose eye points are rougher")
                detector = "haar"
        if detector == "haar":
            found += haar_faces(cv2, gray, "face")
    if a.what in ("cats", "all"):
        found += haar_faces(cv2, gray, "cat")

    def area(f):
        b = f["box"]
        return (b[2] - b[0]) * (b[3] - b[1])

    kept = []
    for f in sorted(found, key=lambda f: -area(f)):
        if all(overlap(f["box"], k["box"]) < 0.4 for k in kept):
            kept.append(f)
    kept.sort(key=lambda f: f["box"][0])  # left to right, so numbering is stable
    if not kept:
        print(f"nothing found in {a.image}; pick the box from the grid instead")
        return

    annotated = im.copy()
    d = ImageDraw.Draw(annotated)
    fnt = font(max(14, min(W, H) // 30))

    def dot(p, color, r=4):
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)

    for i, f in enumerate(kept, 1):
        x1, y1, x2, y2 = f["box"]
        score = f" score {f['score']:.2f}" if f["score"] is not None else ""
        print(f"{f['kind']} {i}: box {x1} {y1} {x2} {y2} ({x2 - x1}x{y2 - y1}){score}")
        print(f"head {i}: box {' '.join(map(str, f['head']))}   <- hair to neck; use for cutout and --fit-box")
        print(f"oval {i}: box {' '.join(map(str, f['oval']))}   <- brows to chin; `cutout --oval --box` for a face-only swap")
        (ex1, ey1), (ex2, ey2) = f["eyes"]
        print(f"eyes {i}{' (estimated)' if f['estimated'] else ''}: {ex1} {ey1} {ex2} {ey2}")
        if "nose" in f:
            (mx1, my1), (mx2, my2) = f["mouth"]
            print(f"nose {i}: {f['nose'][0]} {f['nose'][1]}")
            print(f"mouth {i}: {mx1} {my1} {mx2} {my2}   (corners)")
            print(f"chin {i}: {f['chin'][0]} {f['chin'][1]}")
            print(f"roll {i}: {f['roll']:+.1f} deg   (clockwise tilt; paste --rotate <piece roll - target roll> to match)")
        d.rectangle(f["box"], outline=(255, 0, 0), width=2)
        d.rectangle(f["head"], outline=(255, 0, 255), width=2)
        d.ellipse(f["oval"], outline=(0, 255, 255), width=2)
        for p in f["eyes"]:
            dot(p, (0, 255, 0))
        if "nose" in f:
            for p in (f["nose"], *f["mouth"]):
                dot(p, (255, 255, 0), 3)
            dot(f["chin"], (255, 140, 0))
        label(d, (f["head"][0] + 4, f["head"][1] + 4), str(i), fnt)
    out = out_path(None, f"{Path(a.image).stem}_faces.png")
    annotated.save(out)
    print(f"annotated: {out}   (red = face, magenta = head, cyan = oval, green = eyes, "
          "yellow = nose/mouth, orange = chin)")


# --------------------------------------------------------------- commands

def cmd_prep(a):
    im = open_rgb(a.image)
    w, h = im.size
    scale = min(1.0, a.max / max(w, h))
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    work = out_path(a.out, f"{Path(a.image).stem}_work.png")
    grid = work.with_name(work.stem + "_grid.png")
    im.save(work)
    draw_grid(im).save(grid)
    print(f"work: {work}")
    print(f"grid: {grid}")
    print(f"size: {im.width}x{im.height}")


def dilate(alpha, n):
    """Grow a hard mask by n px with a round brush (square if OpenCV is missing)."""
    try:
        import cv2
        import numpy as np
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * n + 1, 2 * n + 1))
        return Image.fromarray(cv2.dilate(np.array(alpha), k))
    except ImportError:
        return alpha.filter(ImageFilter.MaxFilter(2 * n + 1))


def cmd_cutout(a):
    src = Image.open(a.image)
    src = ImageOps.exif_transpose(src)
    im = src.convert("RGBA") if has_alpha(src) else src.convert("RGB")
    box = clamp_box(a.box, im.size) if a.box else (0, 0, im.width, im.height)
    piece = im.crop(box)

    if a.oval:  # the 2010 face-swap-app look: a hard-edged ellipse, no background removal
        alpha = Image.new("L", piece.size, 0)
        ImageDraw.Draw(alpha).ellipse([0, 0, piece.width - 1, piece.height - 1], fill=255)
        piece = piece.convert("RGBA")
        piece.putalpha(alpha)
    elif a.no_ai:
        piece = piece.convert("RGBA")
    else:
        try:
            from rembg import new_session, remove
        except ImportError:
            sys.exit('rembg is not installed. Run this script with `uv run badshop.py ...`, or:  '
                     'pip install "rembg[cpu]"\n(or rerun with --no-ai to paste the plain rectangle)')
        mask = remove(piece.convert("RGB"), session=new_session(a.model)).getchannel("A")
        alpha = mask.point(lambda v: 255 if v >= a.threshold else 0)
        if a.grow:
            alpha = alpha.filter(ImageFilter.MaxFilter(2 * a.grow + 1))
        piece = piece.convert("RGBA")  # keep the original pixels, so a grown mask shows real old background
        piece.putalpha(alpha)

    opaque = piece.getbbox()
    if opaque is None:
        sys.exit("nothing was kept: the background remover found no subject in that box. "
                 "Try a bigger box, a different --model, or --no-ai.")
    piece = piece.crop(opaque)
    hist = piece.getchannel("A").histogram()
    coverage = sum(hist[1:]) / (piece.width * piece.height)

    if a.sticker:  # thick flat outline behind the shape, like a sticker-pack cutout
        n = a.sticker
        padded = Image.new("RGBA", (piece.width + 2 * n + 2, piece.height + 2 * n + 2), (0, 0, 0, 0))
        padded.paste(piece, (n + 1, n + 1))
        hard = padded.getchannel("A").point(lambda v: 255 if v else 0)
        backing = Image.new("RGBA", padded.size, rgb(a.sticker_color) + (255,))
        backing.putalpha(dilate(hard, n))
        piece = Image.alpha_composite(backing, padded)

    out = out_path(a.out, f"{Path(a.image).stem}_cutout.png")
    piece.save(out)
    print(f"cutout: {out}")
    print(f"size: {piece.width}x{piece.height}")
    print(f"opaque: {coverage:.0%} of the cutout's bounding box")
    if coverage < 0.15:
        print("warning: very little was kept; the box may have missed the subject")


def cmd_paste(a):
    base = open_rgb(a.base).convert("RGBA")
    piece = Image.open(a.piece).convert("RGBA")
    if a.flip:
        piece = ImageOps.mirror(piece)
    if not (a.width or a.fit_box):
        sys.exit("give --width W (or --fit-box X1 Y1 X2 Y2)")
    if not (a.at or a.fit_box or a.repeat):
        sys.exit("give --at X Y (or --fit-box, or --repeat)")

    def scaled(width, height=None):
        w = max(1, round(width))
        h = max(1, round(height if height else piece.height * w / piece.width))
        return piece.resize((w, h), Image.NEAREST)

    if a.repeat:
        rng = random.Random(a.seed)
        x1, y1, x2, y2 = clamp_box(a.region, base.size) if a.region else (0, 0, base.width, base.height)
        for _ in range(a.repeat):
            p = scaled(a.width * rng.uniform(0.5, 1.5))
            if rng.random() < 0.5:
                p = ImageOps.mirror(p)
            p = p.rotate(rng.uniform(-15, 15), resample=Image.NEAREST, expand=True)
            cx, cy = rng.randint(x1, x2), rng.randint(y1, y2)
            base.paste(p, (cx - p.width // 2, cy - p.height // 2), p)
        placed = f"{a.repeat} copies scattered over ({x1}, {y1})-({x2}, {y2}), seed {a.seed}"
    else:
        if a.fit_box:
            bx1, by1, bx2, by2 = a.fit_box
            bw, bh = abs(bx2 - bx1), abs(by2 - by1)
            s = max(bw / piece.width, bh / piece.height) * a.scale  # cover the box, then oversize by --scale
            p = scaled(piece.width * s, piece.height * s)
            if a.rotate:
                p = p.rotate(a.rotate, resample=Image.NEAREST, expand=True)
            x, y = min(bx1, bx2) + bw // 2 - p.width // 2, min(by1, by2) + bh // 2 - p.height // 2
        else:
            p = scaled(a.width, a.height)
            if a.rotate:
                p = p.rotate(a.rotate, resample=Image.NEAREST, expand=True)
            x, y = a.at
            if a.anchor == "center":
                x, y = x - p.width // 2, y - p.height // 2
            elif a.anchor == "bottom":
                x, y = x - p.width // 2, y - p.height
        base.paste(p, (x, y), p)  # hard alpha: no blending, no shadow, no color match
        placed = f"piece placed with top-left at ({x}, {y}), {p.width}x{p.height} after scaling"

    out = out_path(a.out, "result.png")
    base.convert("RGB").save(out)
    print(f"result: {out}")
    print(f"size: {base.width}x{base.height}")
    print(placed)


def cmd_text(a):
    im = open_rgb(a.image)
    W, H = im.size
    text = a.text.upper() if a.style == "impact" else a.text
    probe = ImageDraw.Draw(im)
    color = a.color or ("#46147a" if a.style == "wordart" else "red")
    size = a.size or {"impact": W // 9, "wordart": W // 10}.get(a.style, W // 12)
    while True:
        fnt, used = load_font(a.style, size, a.font)
        lines = wrap_text(probe, text, fnt, W - 2 * a.margin)
        if a.size or len(lines) <= 3 or size <= W // 22:  # auto-size: shrink until it fits in 3 lines
            break
        size = int(size * 0.85)
    layer = render_text(lines, fnt, a.style, color)
    if a.rotate:
        layer = layer.rotate(a.rotate, resample=Image.BICUBIC, expand=True)
    if a.at:
        x, y = a.at[0] - layer.width // 2, a.at[1] - layer.height // 2
    elif a.bottom:
        x, y = (W - layer.width) // 2, H - layer.height - a.margin
    else:
        x, y = (W - layer.width) // 2, a.margin
    im.paste(layer, (x, y), layer)
    out = out_path(a.out, "result.png")
    im.save(out)
    print(f"result: {out}")
    print(f"text: {len(lines)} line(s), {a.style} style, font {used}, size {size}px, at top-left ({x}, {y})")


def cmd_draw(a):
    im = open_rgb(a.image)
    d = ImageDraw.Draw(im)
    color, width, n = rgb(a.color), a.width, 0
    for (x, y, r) in a.circle or []:
        d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=width)
        n += 1
    for (x1, y1, x2, y2) in a.rect or []:
        d.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], outline=color, width=width)
        n += 1
    for (x1, y1, x2, y2) in a.line or []:
        d.line([(x1, y1), (x2, y2)], fill=color, width=width)
        n += 1
    for (x1, y1, x2, y2) in a.arrow or []:
        d.line([(x1, y1), (x2, y2)], fill=color, width=width)
        ang, L = math.atan2(y2 - y1, x2 - x1), 4 * width + 6
        tips = [(x2 - L * math.cos(ang + s), y2 - L * math.sin(ang + s)) for s in (-0.45, 0.45)]
        d.polygon([(x2, y2), *tips], fill=color)
        n += 1
    if not n:
        sys.exit("nothing to draw: give --circle X Y R, --arrow X1 Y1 X2 Y2, --line ... or --rect ...")
    out = out_path(a.out, "result.png")
    im.save(out)
    print(f"result: {out}")
    print(f"drew {n} shape(s) in {a.color}, {width}px")


def cmd_censor(a):
    im = open_rgb(a.image)
    for box in a.box:
        x1, y1, x2, y2 = clamp_box(box, im.size)
        region = im.crop((x1, y1, x2, y2))
        w, h = region.size
        if a.style == "bar":
            region = Image.new("RGB", (w, h), "black")
        elif a.style == "blur":
            region = region.filter(ImageFilter.GaussianBlur(a.block))
        else:  # pixelate
            small = region.resize((max(1, w // a.block), max(1, h // a.block)), Image.BILINEAR)
            region = small.resize((w, h), Image.NEAREST)
        im.paste(region, (x1, y1))
    out = out_path(a.out, "result.png")
    im.save(out)
    print(f"result: {out}")
    print(f"censored {len(a.box)} region(s), style {a.style}")


def cmd_eyes(a):
    im = open_rgb(a.image).convert("RGBA")
    W, H = im.size
    size = a.size or max(6, W // 45)
    L = 3 * max(W, H)
    rad = math.radians(a.angle)
    dx, dy = math.cos(rad), -math.sin(rad)
    color = rgb(a.color)
    hot = tuple(min(255, c + (255 - c) * 2 // 3) for c in color)
    layers = [  # (line width, blur radius, fill): wide soft glow, the beam, a hot core
        (3 * size, 2 * size, color + (200,)),
        (size, max(1, size // 3), color + (255,)),
        (max(1, size // 3), 0, hot + (255,)),
    ]
    for width, blur, fill in layers:
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for (x, y) in a.at:
            d.line([(x, y), (x + dx * L, y + dy * L)], fill=fill, width=width)
            r = width * 0.8
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
        if blur:
            layer = layer.filter(ImageFilter.GaussianBlur(blur))
        im = Image.alpha_composite(im, layer)
    out = out_path(a.out, "result.png")
    im.convert("RGB").save(out)
    print(f"result: {out}")
    print(f"laser eyes at {a.at}, angle {a.angle}, size {size}px")


def cmd_warp(a):
    cv2, np = need_cv2()
    arr = np.array(open_rgb(a.image))
    H, W = arr.shape[:2]
    ys, xs = np.indices((H, W), dtype=np.float32)
    for (cx, cy, r) in a.at:
        dx, dy = xs - cx, ys - cy
        d = np.sqrt(dx * dx + dy * dy) / max(1, r)
        # sample from d**strength of the way out: >0 magnifies the middle (bulge), <0 shrinks it (pinch)
        f = np.where(d < 1, np.power(np.maximum(d, 1e-3), a.strength), 1.0).astype(np.float32)
        arr = cv2.remap(arr, cx + dx * f, cy + dy * f, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
    out = out_path(a.out, "result.png")
    Image.fromarray(arr).save(out)
    print(f"result: {out}")
    print(f"{'bulged' if a.strength > 0 else 'pinched'} {len(a.at)} spot(s), strength {a.strength}")


def cmd_flare(a):
    im = open_rgb(a.image)
    W, H = im.size
    x, y = a.at
    R = a.size or min(W, H) // 6
    glow = Image.new("RGB", im.size, 0)
    ImageDraw.Draw(glow).ellipse([x - R, y - R, x + R, y + R], fill=(255, 235, 190))
    glow = glow.filter(ImageFilter.GaussianBlur(R / 2))
    core = Image.new("RGB", im.size, 0)
    cd = ImageDraw.Draw(core)
    r = R // 4
    cd.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
    cd.line([(x - 4 * R, y), (x + 4 * R, y)], fill=(255, 220, 170), width=max(2, R // 14))
    core = core.filter(ImageFilter.GaussianBlur(max(1, R // 16)))
    ghosts = Image.new("RGB", im.size, 0)
    gd = ImageDraw.Draw(ghosts)
    vx, vy = W / 2 - x, H / 2 - y  # ghosts march from the light through the middle of the frame
    for t, rr, col in [(0.45, 0.22, (40, 140, 60)), (0.8, 0.10, (150, 70, 30)), (1.15, 0.35, (30, 60, 150)),
                       (1.5, 0.16, (140, 40, 110)), (1.9, 0.55, (110, 100, 40))]:
        gx, gy, gr = x + vx * t, y + vy * t, R * rr
        gd.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=col)
        gd.ellipse([gx - gr * 1.15, gy - gr * 1.15, gx + gr * 1.15, gy + gr * 1.15], outline=col, width=2)
    ghosts = ghosts.filter(ImageFilter.GaussianBlur(2))
    for layer in (glow, core, ghosts):
        im = ImageChops.screen(im, layer)
    out = out_path(a.out, "result.png")
    im.save(out)
    print(f"result: {out}")
    print(f"lens flare at ({x}, {y}), size {R}px")


def cmd_sparkle(a):
    im = open_rgb(a.image).convert("RGBA")
    W, H = im.size
    rng = random.Random(a.seed)
    size = a.size or max(12, min(W, H) // 18)
    spots = [(x, y, size) for (x, y) in a.at or []]
    if a.repeat:
        x1, y1, x2, y2 = clamp_box(a.region, im.size) if a.region else (0, 0, W, H)
        spots += [(rng.randint(x1, x2), rng.randint(y1, y2), size * rng.uniform(0.5, 1.4)) for _ in range(a.repeat)]
    if not spots:
        sys.exit("give --at X Y (repeatable) or --repeat N")
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    stars = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gd, sd = ImageDraw.Draw(glow), ImageDraw.Draw(stars)
    color = rgb(a.color)
    for (x, y, s) in spots:
        g = s * 0.45
        gd.ellipse([x - g, y - g, x + g, y + g], fill=color + (190,))
        k = s * 0.14  # four long points, four pinched waists
        sd.polygon([(x, y - s), (x + k, y - k), (x + s, y), (x + k, y + k),
                    (x, y + s), (x - k, y + k), (x - s, y), (x - k, y - k)], fill=(255, 255, 255, 255))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(size / 5)))
    im = Image.alpha_composite(im, stars)
    out = out_path(a.out, "result.png")
    im.convert("RGB").save(out)
    print(f"result: {out}")
    print(f"{len(spots)} sparkle(s), size about {size}px")


WATERMARKS = ("hypercam", "bandicam", "ifunny", "mematic")


def cmd_watermark(a):
    im = open_rgb(a.image).convert("RGBA")
    marks = list(a.names) + (["custom"] if a.text else [])
    if not marks:
        sys.exit(f"name a watermark ({', '.join(WATERMARKS)}) or give --text")
    for name in marks:
        W, H = im.size
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if name == "hypercam":  # black system-font text jammed in the top-left corner
            fnt, _ = load_font("plain", max(12, W // 40))
            d.text((4, 2), "Unregistered HyperCam 2", font=fnt, fill=(0, 0, 0, 255))
        elif name == "bandicam":
            fnt, _ = load_font("bold", max(14, W // 20))
            parts = [("www.", (255, 255, 255)), ("BANDICAM", (35, 140, 255)), (".com", (255, 255, 255))]
            total = sum(d.textlength(t, font=fnt) for t, _ in parts)
            x = (W - total) / 2
            for t, col in parts:
                d.text((x, 4), t, font=fnt, fill=col + (215,), stroke_width=2, stroke_fill=(20, 20, 20, 215))
                x += d.textlength(t, font=fnt)
        elif name == "ifunny":  # a dark strip bolted onto the bottom of the picture
            bar = max(20, H // 26)
            grown = Image.new("RGBA", (W, H + bar), (29, 29, 29, 255))
            grown.paste(im, (0, 0))
            im, layer = grown, Image.new("RGBA", grown.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            fnt, _ = load_font("bold", int(bar * 0.62))
            tw = d.textlength("ifunny.co", font=fnt)
            x0, y0 = W - tw - bar * 1.3, H + bar * 0.14
            d.rectangle([x0 - bar * 0.9, H + bar * 0.18, x0 - bar * 0.25, H + bar * 0.82], fill=(255, 204, 0, 255))
            d.text((x0, y0), "ifunny.co", font=fnt, fill=(255, 255, 255, 255))
        elif name == "mematic":
            fnt, _ = load_font("bold", max(12, W // 34))
            t = "Made with Mematic"
            d.text(((W - d.textlength(t, font=fnt)) / 2, H - fnt.size * 1.6), t, font=fnt,
                   fill=(255, 255, 255, 200), stroke_width=1, stroke_fill=(0, 0, 0, 160))
        else:
            fnt, _ = load_font("bold", max(12, W // 30))
            tw = d.textlength(a.text, font=fnt)
            x = 8 if a.corner[1] == "l" else W - tw - 8
            y = 6 if a.corner[0] == "t" else H - fnt.size * 1.4
            d.text((x, y), a.text, font=fnt, fill=(255, 255, 255, 170), stroke_width=2, stroke_fill=(0, 0, 0, 120))
        im = Image.alpha_composite(im, layer)
    out = out_path(a.out, "result.png")
    im.convert("RGB").save(out)
    print(f"result: {out}")
    print(f"watermarks: {', '.join(marks)}")


FILTERS = {
    "emboss": lambda im: im.filter(ImageFilter.EMBOSS),
    "edges": lambda im: im.filter(ImageFilter.FIND_EDGES),
    "contour": lambda im: im.filter(ImageFilter.CONTOUR),
    "solarize": lambda im: ImageOps.solarize(im, threshold=128),
    "posterize": lambda im: ImageOps.posterize(im, 3),
    "invert": ImageOps.invert,
    "grayscale": lambda im: ImageOps.grayscale(im).convert("RGB"),
    "sepia": lambda im: ImageOps.colorize(ImageOps.grayscale(im), (50, 25, 0), (255, 240, 200)),
    "blur": lambda im: im.filter(ImageFilter.GaussianBlur(6)),
    "sharpen": lambda im: im.filter(ImageFilter.UnsharpMask(radius=3, percent=400, threshold=0)),
    "oilpaint": lambda im: im.filter(ImageFilter.ModeFilter(9)),
}


def cmd_filter(a):
    im = open_rgb(a.image)
    for name in a.names:
        im = FILTERS[name](im)
    out = out_path(a.out, "result.png")
    im.save(out)
    print(f"result: {out}")
    print(f"applied: {', '.join(a.names)}")


def jpeg_cycle(im, quality):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def cmd_save(a):
    im = open_rgb(a.image)
    if a.lowres and a.lowres < 1:
        w, h = im.size
        im = im.resize((max(1, int(w * a.lowres)), max(1, int(h * a.lowres))), Image.BILINEAR)
        im = im.resize((w, h), Image.NEAREST)
    for _ in range(max(0, a.passes - 1)):  # recompress for extra artifacts
        im = jpeg_cycle(im, a.quality)
    if a.gif:
        out = final_path(a.out, a.image, "", ".gif", a.name)
        im.quantize(colors=a.colors, dither=Image.Dither.FLOYDSTEINBERG).save(out)
        print(f"saved: {out}")
        print(f"size: {im.width}x{im.height}, gif with {a.colors} colors, dithered")
        return
    out = final_path(a.out, a.image, "", ".jpg", a.name)
    im.save(out, "JPEG", quality=a.quality)
    print(f"saved: {out}")
    print(f"size: {im.width}x{im.height}, jpeg quality {a.quality}, {a.passes} pass(es)")


def deepfry(im, level, tint=True):
    """The deep-fried meme look, scaled by level 1 (lightly toasted) to 5 (nuked)."""
    t = (max(1, min(5, level)) - 1) / 4

    def lerp(lo, hi):
        return lo + (hi - lo) * t

    if tint:  # push reds and yellows up, blues down
        r, g, b = im.split()
        r = r.point(lambda v: min(255, int(v * lerp(1.06, 1.25) + lerp(6, 22))))
        g = g.point(lambda v: min(255, int(v * lerp(1.0, 1.05))))
        b = b.point(lambda v: int(v * lerp(0.92, 0.65)))
        im = Image.merge("RGB", (r, g, b))

    im = ImageEnhance.Color(im).enhance(lerp(1.7, 4.0))
    im = ImageEnhance.Contrast(im).enhance(lerp(1.35, 2.8))
    for _ in range(round(lerp(1, 5))):  # ringing halos around every edge
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=0))

    noise = Image.effect_noise(im.size, lerp(6, 34)).convert("RGB")  # gaussian grain centred at 128
    im = ImageChops.add(im, noise, scale=1.0, offset=-128)

    w, h = im.size
    shrink = lerp(1.0, 0.55)
    if shrink < 1:  # low-res upscale before the JPEG rounds makes the blocks bigger
        im = im.resize((max(1, int(w * shrink)), max(1, int(h * shrink))), Image.BILINEAR)
        im = im.resize((w, h), Image.BICUBIC)

    quality = round(lerp(22, 4))
    for _ in range(round(lerp(2, 7))):
        im = jpeg_cycle(im, quality)
        im = im.filter(ImageFilter.SHARPEN)  # re-sharpen between rounds so the blocks get crispy
    return im, quality


def cmd_deepfry(a):
    im = open_rgb(a.image)
    im, quality = deepfry(im, a.level, tint=not a.no_tint)
    out = final_path(a.out, a.image, "_deepfried", ".jpg", a.name)
    im.save(out, "JPEG", quality=quality)
    print(f"deepfried: {out}")
    print(f"size: {im.width}x{im.height}, level {a.level}")


def cmd_animate(a):
    sources = [open_rgb(p) for p in a.images]
    size = sources[0].size
    sources = [s if s.size == size else s.resize(size, Image.NEAREST) for s in sources]
    W, H = size
    n = a.frames or {"none": len(sources), "shake": 8, "flash": 6, "zoom": 14, "spin": 12}[a.effect]
    n = max(n, len(sources))
    rng = random.Random(a.seed)
    cx, cy = a.at or (W // 2, H // 2)
    frames = []
    for k in range(n):
        f = sources[k % len(sources)]
        t = k / max(1, n - 1)
        if a.effect == "shake":
            amp = int(a.amount or max(4, W // 50))
            f = ImageChops.offset(f, rng.randint(-amp, amp), rng.randint(-amp, amp))
        elif a.effect == "flash" and k % 2:
            f = ImageOps.invert(f)
        elif a.effect == "zoom":
            z = 1 + t * ((a.amount or 3.0) - 1)
            zw, zh = W / z, H / z
            x0 = min(max(0, cx - zw / 2), W - zw)
            y0 = min(max(0, cy - zh / 2), H - zh)
            f = f.resize(size, Image.NEAREST, box=(x0, y0, x0 + zw, y0 + zh))
        elif a.effect == "spin":
            f = f.rotate(-360 * k / n, resample=Image.NEAREST, fillcolor=(0, 0, 0))
        if a.fry:  # zoom ramps the frying up as it closes in; everything else fries at a constant level
            f, _ = deepfry(f, 1 + round(t * (a.fry - 1)) if a.effect == "zoom" else a.fry)
        frames.append(f.quantize(colors=a.colors, dither=Image.Dither.FLOYDSTEINBERG))
    if a.effect == "zoom" and a.hold:
        frames += [frames[-1]] * a.hold
    out = final_path(a.out, a.images[0], f"_{a.effect}", ".gif", a.name)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=a.delay, loop=0, optimize=False)
    print(f"animated: {out}")
    print(f"size: {W}x{H}, {len(frames)} frames at {a.delay}ms, effect {a.effect}"
          + (f", fried to level {a.fry}" if a.fry else ""))


def cmd_info(a):
    im = open_rgb(a.image)
    print(f"{a.image}: {im.width}x{im.height}")


# ---------------------------------------------------------------- recipes

NOT_RECORDED = {"info", "find", "recipe", "run", "fetch", "wiki", "emoji", "template"}


def output_of(argv):
    for flag in ("-o", "--out"):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return argv[argv.index(flag) + 1]
    return None


def record(argv):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as fh:
        fh.write(json.dumps({"argv": argv, "time": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")


def cmd_recipe(a):
    if a.clear:
        HISTORY.unlink(missing_ok=True)
        print(f"cleared: {HISTORY}")
        return
    entries = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()] if HISTORY.exists() else []
    if a.last:
        entries = entries[-a.last:]
    if not entries:
        sys.exit(f"no history in {HISTORY} yet; run some editing commands first")
    # A re-run that writes the same -o file replaces the earlier attempt but keeps its place in line,
    # so the corrections made along the way collapse into one clean pipeline.
    slots, order = {}, []
    for i, e in enumerate(entries):
        key = output_of(e["argv"]) or f"#{i}"
        if key not in slots:
            order.append(key)
        slots[key] = e["argv"]
    steps = [slots[k] for k in order]
    out = out_path(a.out, "recipe.json")
    out.write_text(json.dumps({"vars": {}, "steps": steps}, indent=2, ensure_ascii=False) + "\n")
    print(f"recipe: {out}")
    print(f"{len(steps)} step(s) from {len(entries)} logged command(s)")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {shlex.join(s)}")
    print('to parametrize: put "{name}" in any argument and add name to "vars", then `run --set name=value`')


def cmd_run(a):
    global RECORDING
    data = json.loads(Path(a.recipe).read_text())
    variables = {k: str(v) for k, v in data.get("vars", {}).items()}
    for s in a.set or []:
        k, sep, v = s.partition("=")
        if not sep:
            sys.exit(f"--set wants name=value, got {s!r}")
        variables[k] = v
    steps = data["steps"]

    def fill(arg):
        return re.sub(r"\{(\w+)\}", lambda m: variables.get(m.group(1), m.group(0)), str(arg))

    RECORDING = False
    for i, argv in enumerate(steps, 1):
        if i < a.from_step:
            continue
        argv = [fill(x) for x in argv]
        print(f"== step {i}/{len(steps)}: {shlex.join(argv)}")
        try:
            main(argv)
        except SystemExit as e:
            if e.code not in (None, 0):
                print(f"step {i} failed", file=sys.stderr)
                raise


# ------------------------------------------------------------------- main

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="badshop.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    box4 = dict(type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    final_help = f"default {FINAL_DIR}/<name>, never overwriting"

    s = sub.add_parser("prep", help="make a small working copy plus a gridded copy")
    s.add_argument("image")
    s.add_argument("--max", type=int, default=1000, help="longest side in px (default 1000)")
    s.add_argument("-o", "--out", help="path for the working copy (default badshop_work/<name>_work.png)")
    s.set_defaults(fn=cmd_prep)

    s = sub.add_parser("fetch", help="search Commons + Openverse, download an image/page URL, or grab the clipboard")
    s.add_argument("query", nargs="?", help='search words like "mona lisa painting", or an image or web page URL')
    s.add_argument("--source", choices=["all", "commons", "openverse"], default="all",
                   help="where to search (default all: Wikimedia Commons and Openverse, interleaved)")
    s.add_argument("-n", type=int, default=6, choices=range(1, 13), metavar="1-12",
                   help="how many candidates to download (default 6)")
    s.add_argument("--clipboard", action="store_true", help="save the image (or image link) on the clipboard")
    s.add_argument("-o", "--out", help="output path (URL and clipboard modes; searches go to badshop_work/fetch/)")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("wiki", help="lead images of Wikipedia articles matching a name")
    s.add_argument("title", help='a person, place or thing, e.g. "Abraham Lincoln"')
    s.add_argument("-n", type=int, default=4, choices=range(1, 9), metavar="1-8",
                   help="how many matching articles (default 4; the first is usually the exact one)")
    s.add_argument("--lang", default="en", help="Wikipedia language code (default en)")
    s.set_defaults(fn=cmd_wiki)

    s = sub.add_parser("emoji", help="transparent Twemoji PNGs by character, hex code, or name")
    s.add_argument("emoji", nargs="+", help=f"e.g. 😂 1f480 skull; names: {', '.join(sorted(EMOJI_NAMES))}")
    s.add_argument("--size", type=int, help="nearest-neighbor upscale to this many px (default: the 72px original)")
    s.set_defaults(fn=cmd_emoji)

    s = sub.add_parser("template", help="classic meme templates from Imgflip")
    s.add_argument("name", nargs="?", help='e.g. "drake", "distracted boyfriend", "two buttons"')
    s.add_argument("-n", type=int, default=3, choices=range(1, 9), metavar="1-8",
                   help="how many best matches to download (default 3)")
    s.add_argument("--list", action="store_true", help="print all template names instead")
    s.set_defaults(fn=cmd_template)

    s = sub.add_parser("find", help="locate faces and print head, oval, eye, nose, mouth, chin and tilt")
    s.add_argument("image")
    s.add_argument("--what", choices=["faces", "cats", "all"], default="faces",
                   help="faces (default, human), cats, or all")
    s.add_argument("--detector", choices=["auto", "yunet", "haar"], default="auto",
                   help="auto (default): YuNet with landmarks, falling back to Haar cascades")
    s.add_argument("--min-score", type=float, default=0.7,
                   help="YuNet confidence cutoff 0-1 (default 0.7; lower finds more, and more junk)")
    s.set_defaults(fn=cmd_find)

    s = sub.add_parser("cutout", help="crop a box and remove its background with hard edges")
    s.add_argument("image")
    s.add_argument("--box", **box4, help="rectangle to cut, pixel coords; omit to use the whole image")
    s.add_argument("--model", default="u2net",
                   help="rembg model: u2net (default, fast), birefnet-general (cleaner), u2net_human_seg, isnet-anime")
    s.add_argument("--threshold", type=int, default=128, help="alpha cutoff 0-255 (default 128)")
    s.add_argument("--grow", type=int, default=0, help="dilate the mask N px to drag in a halo of old background")
    s.add_argument("--no-ai", action="store_true", help="skip background removal; keep the whole rectangle")
    s.add_argument("--oval", action="store_true",
                   help="cut a hard-edged ellipse filling the box instead (face-only swap; use `find`'s oval box)")
    s.add_argument("--sticker", type=int, metavar="N", help="add an N px flat outline around the shape")
    s.add_argument("--sticker-color", default="white", help="outline color for --sticker (default white)")
    s.add_argument("-o", "--out", help="default badshop_work/<name>_cutout.png")
    s.set_defaults(fn=cmd_cutout)

    s = sub.add_parser("paste", help="paste a cutout onto a base image")
    s.add_argument("base")
    s.add_argument("piece")
    s.add_argument("--at", type=int, nargs=2, metavar=("X", "Y"), help="where the anchor goes, pixel coords")
    s.add_argument("--anchor", choices=["topleft", "center", "bottom"], default="topleft",
                   help="which point of the piece --at refers to (default topleft; bottom = bottom-center)")
    s.add_argument("--width", type=float, help="width to scale the piece to")
    s.add_argument("--height", type=float, help="height; omit to keep the aspect ratio, set to squash or stretch")
    s.add_argument("--fit-box", **box4, help="instead of --at/--width: scale and center the piece to cover this box")
    s.add_argument("--scale", type=float, default=1.0, help="with --fit-box, oversize factor (1.3 = 30%% too big)")
    s.add_argument("--rotate", type=float, default=0, help="degrees counter-clockwise")
    s.add_argument("--flip", action="store_true", help="mirror the piece horizontally")
    s.add_argument("--repeat", type=int, help="scatter this many random copies (size 0.5-1.5x --width) instead")
    s.add_argument("--region", **box4, help="with --repeat, only scatter inside this box")
    s.add_argument("--seed", type=int, default=1, help="with --repeat, change for a different scatter")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_paste)

    s = sub.add_parser("text", help="Impact caption, MS Paint text, or WordArt")
    s.add_argument("image")
    s.add_argument("text", help="the words; use \\n for a manual line break")
    s.add_argument("--style", choices=["impact", "paint", "wordart"], default="impact",
                   help="impact: white, black outline, uppercase; paint: colored with a hard shadow; "
                        "wordart: rainbow face with a 3D extrusion")
    s.add_argument("--bottom", action="store_true", help="bottom caption (default is top)")
    s.add_argument("--at", type=int, nargs=2, metavar=("X", "Y"), help="center the text on this point instead")
    s.add_argument("--size", type=int, help="font size in px (default: fits the image width)")
    s.add_argument("--color", help="paint text color (default red), or wordart extrusion color (default purple)")
    s.add_argument("--rotate", type=float, default=0, help="degrees counter-clockwise")
    s.add_argument("--margin", type=int, default=20)
    s.add_argument("--font", help="path or name of a font file to use instead")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_text)

    s = sub.add_parser("draw", help="MS Paint annotations; repeat any shape option for more")
    s.add_argument("image")
    s.add_argument("--circle", type=int, nargs=3, action="append", metavar=("X", "Y", "R"))
    s.add_argument("--arrow", action="append", **box4)
    s.add_argument("--line", action="append", **box4)
    s.add_argument("--rect", action="append", **box4)
    s.add_argument("--color", default="red")
    s.add_argument("--width", type=int, default=6, help="stroke width in px (default 6)")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_draw)

    s = sub.add_parser("censor", help="pixelate, black-bar or blur rectangles")
    s.add_argument("image")
    s.add_argument("--box", action="append", required=True, **box4)
    s.add_argument("--style", choices=["pixelate", "bar", "blur"], default="pixelate")
    s.add_argument("--block", type=int, default=16, help="pixel size for pixelate, blur radius for blur (default 16)")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_censor)

    s = sub.add_parser("eyes", help="laser eyes")
    s.add_argument("image")
    s.add_argument("--at", type=int, nargs=2, action="append", metavar=("X", "Y"), required=True,
                   help="an eye position; give it twice for two eyes")
    s.add_argument("--angle", type=float, default=155, help="beam direction in degrees, 0 = right, 90 = up (default 155)")
    s.add_argument("--size", type=int, help="beam thickness in px (default: scaled to the image)")
    s.add_argument("--color", default="red")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_eyes)

    s = sub.add_parser("warp", help="bulge or pinch circular spots (giant eyes, huge nose)")
    s.add_argument("image")
    s.add_argument("--at", type=int, nargs=3, action="append", metavar=("X", "Y", "R"), required=True,
                   help="center and radius of a spot; repeatable")
    s.add_argument("--strength", type=float, default=0.6,
                   help="positive bulges, negative pinches (default 0.6; 1.0 is huge, -0.5 is a strong pinch)")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_warp)

    s = sub.add_parser("flare", help="lens flare")
    s.add_argument("image")
    s.add_argument("--at", type=int, nargs=2, metavar=("X", "Y"), required=True, help="where the light is")
    s.add_argument("--size", type=int, help="glow radius in px (default: a sixth of the short side)")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_flare)

    s = sub.add_parser("sparkle", help="clip-art four-point sparkles")
    s.add_argument("image")
    s.add_argument("--at", type=int, nargs=2, action="append", metavar=("X", "Y"), help="a sparkle; repeatable")
    s.add_argument("--repeat", type=int, help="scatter this many at random instead (or as well)")
    s.add_argument("--region", **box4, help="with --repeat, only scatter inside this box")
    s.add_argument("--size", type=int, help="sparkle radius in px (default: scaled to the image)")
    s.add_argument("--color", default="#fff27a", help="glow color (default pale yellow)")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_sparkle)

    s = sub.add_parser("watermark", help="fake screen-recorder / meme-app watermarks")
    s.add_argument("image")
    s.add_argument("names", nargs="*", choices=WATERMARKS, metavar="NAME", help=", ".join(WATERMARKS))
    s.add_argument("--text", help="your own watermark text as well")
    s.add_argument("--corner", choices=["tl", "tr", "bl", "br"], default="br", help="corner for --text (default br)")
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_watermark)

    s = sub.add_parser("filter", help="apply one or more effects, in order")
    s.add_argument("image")
    s.add_argument("names", nargs="+", choices=sorted(FILTERS), metavar="NAME",
                   help=", ".join(sorted(FILTERS)))
    s.add_argument("-o", "--out", help="default badshop_work/result.png")
    s.set_defaults(fn=cmd_filter)

    s = sub.add_parser("save", help="write a low-quality JPEG, or a dithered GIF")
    s.add_argument("image")
    s.add_argument("--quality", type=int, default=35, help="JPEG quality 1-95 (default 35)")
    s.add_argument("--passes", type=int, default=1, help="recompress this many times for more artifacts")
    s.add_argument("--lowres", type=float, help="downscale to this fraction and back up, e.g. 0.3 for potato quality")
    s.add_argument("--gif", action="store_true", help="write a dithered 1999-style GIF instead of a JPEG")
    s.add_argument("--colors", type=int, default=64, help="with --gif, palette size (default 64)")
    s.add_argument("--name", help="file name without extension, saved in the output folder")
    s.add_argument("-o", "--out", help=final_help)
    s.set_defaults(fn=cmd_save)

    s = sub.add_parser("deepfry", help="deep-fried meme treatment, written as a JPEG")
    s.add_argument("image")
    s.add_argument("--level", type=int, default=3, choices=range(1, 6), metavar="1-5",
                   help="1 = lightly toasted, 3 = default, 5 = nuked")
    s.add_argument("--no-tint", action="store_true", help="skip the red/yellow color cast")
    s.add_argument("--name", help="file name without extension, saved in the output folder")
    s.add_argument("-o", "--out", help=final_help)
    s.set_defaults(fn=cmd_deepfry)

    s = sub.add_parser("animate", help="animated GIF from one or more images")
    s.add_argument("images", nargs="+", help="frames cycle through these (e.g. with and without laser eyes)")
    s.add_argument("--effect", choices=["none", "shake", "flash", "zoom", "spin"], default="none")
    s.add_argument("--frames", type=int, help="frame count (default depends on the effect)")
    s.add_argument("--delay", type=int, default=80, help="ms per frame (default 80)")
    s.add_argument("--amount", type=float, help="shake: max px offset; zoom: final zoom factor (default 3)")
    s.add_argument("--at", type=int, nargs=2, metavar=("X", "Y"), help="zoom target (default: the center)")
    s.add_argument("--hold", type=int, default=6, help="zoom: repeat the last frame this many times (default 6)")
    s.add_argument("--fry", type=int, choices=range(1, 6), metavar="1-5",
                   help="deep-fry every frame at this level (zoom ramps up to it)")
    s.add_argument("--colors", type=int, default=128, help="palette size per frame (default 128)")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--name", help="file name without extension, saved in the output folder")
    s.add_argument("-o", "--out", help=final_help)
    s.set_defaults(fn=cmd_animate)

    s = sub.add_parser("recipe", help="write the logged editing commands as a replayable recipe")
    s.add_argument("--last", type=int, help="only use the last N logged commands")
    s.add_argument("--clear", action="store_true", help="forget the history (do this before starting a new meme)")
    s.add_argument("-o", "--out", help="default badshop_work/recipe.json")
    s.set_defaults(fn=cmd_recipe)

    s = sub.add_parser("run", help="replay a recipe")
    s.add_argument("recipe")
    s.add_argument("--set", action="append", metavar="NAME=VALUE", help='fill "{NAME}" in the recipe; repeatable')
    s.add_argument("--from", dest="from_step", type=int, default=1, help="start at this step number")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("info", help="print an image's size")
    s.add_argument("image")
    s.set_defaults(fn=cmd_info)

    a = p.parse_args(argv)
    a.fn(a)
    if RECORDING and a.cmd not in NOT_RECORDED:
        record(argv)


if __name__ == "__main__":
    main()
