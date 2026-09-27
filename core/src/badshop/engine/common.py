"""Image helpers every engine module shares, ported from reference/badshop.py."""

import io
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from badshop.engine.errors import EngineError


# The decoders for images from the web or the clipboard. Pillow's others include EPS, which runs Ghostscript.
# JPEG's decoder also opens MPO (phone photos); "MPO" itself is not a decoder name and Image.open rejects it.
WEB_FORMATS = ("PNG", "JPEG", "GIF", "WEBP")

# The biggest image a parameter may ask the engine to make (a scaled paste, a caption layer, a sticker
# border). Field caps bound each number; this bounds their products (fit_box x scale, a thin piece's height).
MAX_WORK_PIXELS = 50_000_000


def check_size(w: int, h: int) -> None:
    """Refuse, before Pillow tries to allocate it, an image that parameters blew up past the budget."""
    if w * h > MAX_WORK_PIXELS:
        raise EngineError(f"that would make a {w}x{h} image, too big to work with",
                          hint=f"use a smaller size or scale (the limit is {MAX_WORK_PIXELS // 1_000_000} megapixels)")


def load_image(src: Path | bytes, formats: tuple[str, ...] | None = None,
               max_pixels: int | None = None) -> Image.Image:
    """Open a file or bytes upright (EXIF rotation applied), fully loaded, mode and .format preserved.

    `formats` limits the decoders tried (e.g. WEB_FORMATS); None tries every one Pillow has.
    `max_pixels` refuses a bigger image before decoding it, with Pillow's DecompressionBombError
    (which Pillow itself raises above about 179 megapixels)."""
    im = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src, formats=formats)
    if max_pixels is not None and im.width * im.height > max_pixels:
        w, h = im.size
        im.close()
        raise Image.DecompressionBombError(f"Image size ({w}x{h}) exceeds limit of {max_pixels} pixels")
    ImageOps.exif_transpose(im, in_place=True)  # phone photos carry their rotation in EXIF
    im.load()
    return im


def to_rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):  # 16-bit: scale down, don't clip
        im = im.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    return im.convert("RGB")


def has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def fit(im: Image.Image, longest: int) -> tuple[Image.Image, float]:
    """Shrink (never enlarge) so the longest side is at most `longest` px: reference cmd_prep's resize.

    Returns the image and the scale applied; source pixels = output pixels / scale.
    """
    w, h = im.size
    scale = min(1.0, longest / max(w, h))
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    return im, scale


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


def draw_grid(im, major=100, minor=50) -> Image.Image:
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


def clamp_box(box, size) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    w, h = size
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise EngineError(f"box {box} is empty or lies outside the {w}x{h} image",
                          hint="boxes are X1 Y1 X2 Y2 in pixels of this image; "
                               "use find or a grid view to get them")
    return x1, y1, x2, y2


def rgb(color: str) -> tuple[int, int, int]:
    try:
        return ImageColor.getrgb(color)[:3]
    except ValueError:
        raise EngineError(f"unknown color {color!r}",
                          hint="use a name like red or a hex value like #ff00ff") from None


def int_box(box, W, H):
    x1, y1, x2, y2 = box
    return (max(0, round(x1)), max(0, round(y1)), min(W, round(x2)), min(H, round(y2)))


def overlap(a, b) -> float:
    """Intersection over the smaller box's area."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small else 0


def jpeg_cycle(im, quality) -> Image.Image:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def need_cv2():
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise EngineError("OpenCV is not installed",
                          hint='pip install "opencv-python-headless<5" numpy') from e
    return cv2, np
