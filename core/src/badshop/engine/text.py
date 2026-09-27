"""Captions: Impact meme text, MS Paint text and WordArt, ported from reference/badshop.py."""

import glob
import re
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from PIL import Image, ImageChops, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont
from pydantic import AfterValidator, Field

from badshop.engine import assets
from badshop.engine.common import check_size, font, rgb, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Color, ImageRef, Params, Point

SYSTEM_FONT_DIRS = [
    Path("C:/Windows/Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"), Path.home() / "Library/Fonts",
    Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
    Path.home() / ".fonts", Path.home() / ".local/share/fonts",
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
FONT_DOWNLOADS = {  # SIL Open Font License lookalikes, fetched once when nothing better is installed,
    # pinned to the google/fonts commits that last changed them
    "Anton-Regular.ttf": assets.Pinned(
        "https://github.com/google/fonts/raw/e0a8124cf36bb7c32ca68e5d46d6acdbc3df866a/ofl/anton/Anton-Regular.ttf",
        sha256="a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab", size=170812),
    "ComicNeue-Bold.ttf": assets.Pinned(
        "https://github.com/google/fonts/raw/23bf052eb5d01205102d72cba29580df2a38c422/"
        "ofl/comicneue/ComicNeue-Bold.ttf",
        sha256="3e7e5fccfd7e0788f317b43312151c1bd5cf058c9697a8d83eac3939050bd61e", size=55716),
}


def _font_dirs(data_dir: str) -> list[Path]:
    """The reference's FONT_DIRS, with downloaded fonts in the app data dir instead of the XDG cache."""
    return [*SYSTEM_FONT_DIRS, Path(data_dir) / "fonts"]


_font_cache: dict[tuple[str, str | None, str], str | None] = {}


def find_font_file(style: str, explicit: str | None = None) -> str | None:
    """Path (or Pillow-searchable name) of the best font for a style, or None for the built-in one."""
    key = (style, explicit, str(assets.data_dir()))  # a changed BADSHOP_DATA_DIR is searched afresh
    if key in _font_cache:
        return _font_cache[key]
    found, definitive = _find_font_file(*key)
    if definitive:  # not after a failed download: a moment offline must not pin a fallback for good
        _font_cache[key] = found
    return found


def _find_font_file(style: str, explicit: str | None, data_dir: str) -> tuple[str | None, bool]:
    """The font, and whether that answer is definitive (no font download failed on the way)."""
    names = [explicit] if explicit else FONT_CANDIDATES[style]
    definitive = True
    for name in names:
        if Path(name).is_file():
            return name, definitive
        # rglob rejects a pattern with a drive or root (NotImplementedError), so a missing absolute
        # path skips the folder search and falls through to Pillow's search and then the built-in font.
        dirs = [] if Path(name).anchor else _font_dirs(data_dir)
        for d in dirs:
            if d.is_dir():
                hit = next(d.rglob(glob.escape(name)), None)  # a file name, never a pattern
                if hit:
                    return str(hit), definitive
        try:  # Pillow does its own platform search too
            ImageFont.truetype(name, 10)
            return name, definitive
        except OSError:
            pass
        if name in FONT_DOWNLOADS and not explicit:
            try:
                pin = FONT_DOWNLOADS[name]
                return str(assets.cached(f"fonts/{name}", pin.url, sha256=pin.sha256, size=pin.size)), definitive
            except EngineError:
                definitive = False  # offline: keep going down the list, and try the download again next time
    return None, definitive


def load_font(style: str, size: int, explicit: str | None = None) -> tuple[FreeTypeFont, str]:
    path = find_font_file(style, explicit)
    if path is None:
        return font(size), "built-in"
    try:
        return ImageFont.truetype(path, size), Path(path).name
    except OSError:
        raise EngineError(f"{Path(path).name} isn't a font file Pillow can read",
                          hint="use a .ttf or .otf font file") from None


LINE_BREAK = re.compile(r"\\n|\r\n|\r|\n")  # a typed \n (the CLI) or a real newline (JSON, a text box)


def wrap_text(draw, text, fnt, max_width) -> list[str]:
    lines = []
    for para in LINE_BREAK.split(text):
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


def rainbow(size) -> Image.Image:
    """Left-to-right red-to-violet gradient, the WordArt preset everyone picked."""
    w, h = size
    hue = Image.linear_gradient("L").rotate(90).resize((w, h)).point(lambda v: v * 210 // 255)
    full = Image.new("L", (w, h), 255)
    return Image.merge("HSV", (hue, full, full)).convert("RGBA")


def render_text(lines, fnt, style, color) -> Image.Image:
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
    check_size(W, H)
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


def _font_ref(v: str) -> str:
    # The name is searched for under the font folders: no wildcards, and no `..` to climb out of them.
    if re.search(r"[*?\[\]]", v) or ".." in re.split(r"[\\/]", v):
        raise ValueError("give a font file name or path, without wildcards (* ? [ ]) or '..'")
    return v


FontRef = Annotated[str, AfterValidator(_font_ref), Field(max_length=1024)]


class TextParams(Params):
    POSITIONAL: ClassVar = ("image", "text")
    image: ImageRef = Field(description="image to caption")
    text: str = Field(max_length=1000, description="the words; a new line (or a typed \\n) forces a line break")
    style: Literal["impact", "paint", "wordart"] = Field(
        "impact", description="impact: white, black outline, uppercase; paint: colored with a hard "
                              "shadow; wordart: rainbow face with a 3D extrusion")
    bottom: bool = Field(False, description="bottom caption (default is top)")
    at: Point | None = Field(None, description="center the text on this point instead")
    size: int | None = Field(None, ge=4, le=4096, description="font size in px (default: fits the image width)")
    color: Color | None = Field(
        None, description="paint text color (default red), or wordart extrusion color (default purple)")
    rotate: float = Field(0, description="degrees counter-clockwise")
    margin: int = Field(20, ge=0, le=10_000, description="gap from the edge in px")
    font: FontRef | None = Field(None, description="path or name of a font file to use instead")


def caption(p: TextParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_text
    im = to_rgb(image)
    W, H = im.size
    # split before upper-casing: Impact would turn a typed \n into \N, which no longer breaks the line
    text = "\n".join(s.upper() for s in LINE_BREAK.split(p.text)) if p.style == "impact" else p.text
    probe = ImageDraw.Draw(im)
    if p.color:
        rgb(p.color)  # a clean error up front: the paint style hands the color straight to PIL
    color = p.color or ("#46147a" if p.style == "wordart" else "red")
    size = p.size or {"impact": W // 9, "wordart": W // 10}.get(p.style, W // 12)
    while True:
        if size < 1:  # auto-size reached 0: shrinking below 22 px wide, or starting below 9-12 px wide
            raise EngineError("the image is too small for this caption",
                              hint="give size, or caption a bigger image")
        fnt, used = load_font(p.style, size, p.font)
        lines = wrap_text(probe, text, fnt, W - 2 * p.margin)
        if p.size or len(lines) <= 3 or size <= W // 22:  # auto-size: shrink until it fits in 3 lines
            break
        size = int(size * 0.85)
    if not lines:
        raise EngineError("nothing to write", hint="give some words")
    layer = render_text(lines, fnt, p.style, color)
    if p.rotate:
        layer = layer.rotate(p.rotate, resample=Image.BICUBIC, expand=True)
    if p.at:
        x, y = p.at[0] - layer.width // 2, p.at[1] - layer.height // 2
    elif p.bottom:
        x, y = (W - layer.width) // 2, H - layer.height - p.margin
    else:
        x, y = (W - layer.width) // 2, p.margin
    im.paste(layer, (x, y), layer)
    return EngineResult(
        outputs=[Output("result", im, "result.png")],
        lines=[f"text: {len(lines)} line(s), {p.style} style, font {used}, size {size}px, "
               f"at top-left ({x}, {y})"],
    )
