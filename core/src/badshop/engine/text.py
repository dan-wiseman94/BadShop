"""Captions: Impact meme text, MS Paint text and WordArt, ported from reference/badshop.py."""

import glob
import re
import time
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from PIL import Image, ImageChops, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont
from pydantic import AfterValidator, Field

from badshop.engine import assets
from badshop.engine.common import check_size, font, rgb, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, Color, ImageRef, Params, Point

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

# After a font download fails, lookups skip it for this long, so one offline caption (whose auto-size loop
# looks the font up at every size it tries) waits on the network once, not once per size.
DOWNLOAD_RETRY_S = 60.0
_download_failed_at: dict[tuple[str, str], float] = {}  # (font file name, data dir) -> time.monotonic()


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
            key = (name, data_dir)
            failed_at = _download_failed_at.get(key)
            if failed_at is not None and time.monotonic() - failed_at < DOWNLOAD_RETRY_S:
                definitive = False  # it failed moments ago: fall back without waiting on the network again
                continue
            try:
                pin = FONT_DOWNLOADS[name]
                path = assets.cached(f"fonts/{name}", pin.url, sha256=pin.sha256, size=pin.size)
            except EngineError:
                _download_failed_at[key] = time.monotonic()
                definitive = False  # offline: keep going down the list, and try the download again later
                continue
            _download_failed_at.pop(key, None)
            return str(path), definitive
    return None, definitive


def load_font(style: str, size: int, explicit: str | None = None) -> tuple[FreeTypeFont, str]:
    if explicit == "bundled":
        return font(size), "bundled Aileron"
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


def render_text(lines, fnt, style, color, budget: int = 0, align: str = "center", hard_edges: bool = False) -> Image.Image:
    """RGBA layer with the text, tight around it. `budget` is check_size's floor: the pixels of the image
    the text goes on, which the layer may use even past MAX_WORK_PIXELS."""
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
    check_size(W, H, floor=budget)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if hard_edges:
        d.fontmode = "1"
    def line_x(width, offset):
        if align == "left":
            return stroke + 2
        if align == "right":
            return W - offset - width - stroke - 2
        return (W - offset - width) / 2
    if style == "wordart":
        outer, inner = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
        do, di = ImageDraw.Draw(outer), ImageDraw.Draw(inner)
        if hard_edges:
            do.fontmode = di.fontmode = "1"
        for i, line in enumerate(lines):
            x, y = line_x(widths[i], off), stroke + i * lh
            do.text((x, y), line, font=fnt, fill=255, stroke_width=stroke, stroke_fill=255)
            di.text((x, y), line, font=fnt, fill=255)
        if hard_edges:
            outer = outer.point(lambda a: 255 if a >= 128 else 0)
            inner = inner.point(lambda a: 255 if a >= 128 else 0)
        side = Image.new("RGBA", (W, H), rgb(color) + (255,))
        for k in range(depth, 0, -1):  # solid extrusion down and to the right
            layer.paste(side, (0, 0), ImageChops.offset(outer, k, k))
        layer.paste(Image.new("RGBA", (W, H), (0, 0, 0, 255)), (0, 0), outer)
        layer.paste(rainbow((W, H)), (0, 0), inner)
        return layer
    for i, line in enumerate(lines):
        x, y = line_x(widths[i], shadow), stroke + i * lh
        if style == "impact":
            if hard_edges:
                outer, inner = Image.new("1", (W, H)), Image.new("1", (W, H))
                ImageDraw.Draw(outer).text((x, y), line, font=fnt, fill=1, stroke_width=stroke, stroke_fill=1)
                ImageDraw.Draw(inner).text((x, y), line, font=fnt, fill=1)
                layer.paste((0, 0, 0, 255), (0, 0), outer)
                layer.paste((255, 255, 255, 255), (0, 0), inner)
            else:
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
    font: FontRef | None = Field(None, description="bundled uses portable Latin-1 Aileron without downloads; otherwise a font file name or path")
    fit_exact: bool = Field(False, description="shrink until all caption words fit inside the image; refuse clipping")
    preserve_case: bool = Field(False, description="keep the typed capitalization, including with Impact")
    preserve_line_breaks: bool = Field(False, description="keep exact lines and spaces instead of automatic wrapping")
    box: Box | None = Field(None, description="text area inside the image; margin is inset inside this box")
    align: Literal["left", "center", "right"] = "center"
    overflow: Literal["clip", "shrink", "error"] = Field("clip", description="clip keeps legacy placement; shrink fits all words; error refuses overflow")
    frame: Literal["none", "box", "bubble"] = "none"
    frame_padding: int = Field(8, ge=0, le=200)
    frame_color: Color = "#ffffff"
    frame_border: Color = "#000000"
    frame_width: int = Field(2, ge=0, le=40)
    tail: Point | None = Field(None, description="optional speech-bubble tail tip in image coordinates; attaches to the bottom edge")


def caption(p: TextParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_text
    im = to_rgb(image)
    if p.font == "bundled":
        try:
            p.text.encode("latin-1")
        except UnicodeEncodeError:
            raise EngineError("the bundled font supports Latin-1 text", hint="choose a local font for other scripts") from None
    W, H = im.size
    x1, y1, x2, y2 = p.box or (0, 0, W, H)
    if not (0 <= x1 < x2 <= W and 0 <= y1 < y2 <= H):
        raise EngineError("text box must be inside the image with positive width and height")
    padding = p.frame_padding + p.frame_width if p.frame != "none" else 0
    frame_color = rgb(p.frame_color) if p.frame != "none" else None
    frame_border = rgb(p.frame_border) if p.frame != "none" else None
    available_width, available_height = x2 - x1 - 2 * (p.margin + padding), y2 - y1 - 2 * (p.margin + padding)
    if (p.box or p.fit_exact or p.overflow != "clip" or padding) and (available_width <= 0 or available_height <= 0):
        raise EngineError("text margins leave no room for the caption")
    exact = p.fit_exact or p.overflow == "shrink"
    # split before upper-casing: Impact would turn a typed \n into \N, which no longer breaks the line
    text = "\n".join(s.upper() for s in LINE_BREAK.split(p.text)) if p.style == "impact" and not p.preserve_case else p.text
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
        lines = LINE_BREAK.split(text) if p.preserve_line_breaks else wrap_text(probe, text, fnt, available_width)
        if p.size or len(lines) <= 3 or size <= W // 22:  # auto-size: shrink until it fits in 3 lines
            break
        size = int(size * 0.85)
    if not lines or not any(line.strip() for line in lines):
        raise EngineError("nothing to write", hint="give some words")
    # a caption as big as the photo it goes on is never too big, even when the photo is over the budget
    hard_edges = p.font == "bundled" or p.frame != "none"
    layer = render_text(lines, fnt, p.style, color, budget=im.width * im.height, align=p.align, hard_edges=hard_edges)
    if p.rotate:
        layer = layer.rotate(p.rotate, resample=Image.NEAREST if exact or hard_edges else Image.BICUBIC, expand=True)
    if exact:
        while layer.width > available_width or layer.height > available_height:
            size = int(size * 0.85)
            if size < 4:
                raise EngineError("these words cannot fit at a readable size", hint="use fewer words or a larger image")
            fnt, used = load_font(p.style, size, p.font)
            lines = LINE_BREAK.split(text) if p.preserve_line_breaks else wrap_text(probe, text, fnt, available_width)
            layer = render_text(lines, fnt, p.style, color, budget=im.width * im.height, align=p.align, hard_edges=hard_edges)
            if p.rotate:
                layer = layer.rotate(p.rotate, resample=Image.NEAREST, expand=True)
    if p.overflow == "error" and (layer.width > available_width or layer.height > available_height):
        raise EngineError("caption placement would clip words", hint="shrink the text or increase its box")
    if p.frame != "none":
        check_size(layer.width + 2 * padding, layer.height + 2 * padding, floor=W * H)
        framed = Image.new("RGBA", (layer.width + 2 * padding, layer.height + 2 * padding))
        draw = ImageDraw.Draw(framed)
        rect = (0, 0, framed.width - 1, framed.height - 1)
        if p.frame == "bubble":
            draw.rounded_rectangle(rect, radius=min(16, padding), fill=frame_color,
                outline=frame_border if p.frame_width else None, width=p.frame_width)
        else:
            draw.rectangle(rect, fill=frame_color, outline=frame_border if p.frame_width else None, width=p.frame_width)
        framed.paste(layer, (padding, padding), layer)
        layer = framed
    if p.at:
        x, y = p.at[0] - layer.width // 2, p.at[1] - layer.height // 2
    else:
        x = x1 + (x2 - x1 - layer.width) // 2
        if p.align == "left":
            x = x1 + p.margin
        elif p.align == "right":
            x = x2 - p.margin - layer.width
        y = y2 - layer.height - p.margin if p.bottom else y1 + p.margin
    if (exact or p.overflow == "error") and not (x1 <= x and y1 <= y and x + layer.width <= x2 and y + layer.height <= y2):
        raise EngineError("caption placement would clip words", hint="move the caption inside the image")
    bounds = [x, y, x + layer.width, y + layer.height]
    if p.frame == "bubble" and p.tail:
        tx, ty = p.tail
        if not (0 <= tx < W and 0 <= ty < H):
            raise EngineError("speech bubble tail must be inside the image")
        center, bottom = x + layer.width // 2, y + layer.height - 1
        half = max(2, min(12, layer.width // 4))
        draw = ImageDraw.Draw(im)
        draw.polygon([(center - half, bottom), (tx, ty), (center + half, bottom)], fill=frame_color)
        if p.frame_width:
            draw.line([(center - half, bottom), (tx, ty), (center + half, bottom)], fill=frame_border, width=p.frame_width)
        bounds = [min(x, tx), min(y, ty), max(bounds[2], tx + 1), max(bounds[3], ty + 1)]
    im.paste(layer, (x, y), layer)
    return EngineResult(
        outputs=[Output("result", im, "result.png")],
        lines=[f"text: {len(lines)} line(s), {p.style} style, font {used}, size {size}px, "
               f"at top-left ({x}, {y})"],
        data={"element_bounds": bounds},
    )
