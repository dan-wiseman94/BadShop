"""MS Paint annotations, censor bars and laser eyes, ported from reference/badshop.py."""

import math
from typing import ClassVar, Literal

from PIL import Image, ImageDraw, ImageFilter
from pydantic import Field

from badshop.engine.common import clamp_box, rgb, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, Color, ImageRef, Params, Point, Spot


class DrawParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to draw on")
    circle: list[Spot] = Field(default_factory=list, description="circles as X Y R; repeatable")
    arrow: list[Box] = Field(default_factory=list, description="arrows from X1 Y1 to X2 Y2 (head at the end)")
    line: list[Box] = Field(default_factory=list, description="lines X1 Y1 X2 Y2")
    rect: list[Box] = Field(default_factory=list, description="rectangles X1 Y1 X2 Y2")
    color: Color = Field("red", description="stroke color")
    width: int = Field(6, ge=1, description="stroke width in px")


def draw(p: DrawParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_draw
    im = to_rgb(image)
    d = ImageDraw.Draw(im)
    color, width, n = rgb(p.color), p.width, 0
    for (x, y, r) in p.circle:
        if r < 0:  # not in the reference, which crashed in PIL here
            raise EngineError(f"circle radius {r} is negative", hint="circles are X Y R with R >= 0 in pixels")
        d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=width)
        n += 1
    for (x1, y1, x2, y2) in p.rect:
        d.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], outline=color, width=width)
        n += 1
    for (x1, y1, x2, y2) in p.line:
        d.line([(x1, y1), (x2, y2)], fill=color, width=width)
        n += 1
    for (x1, y1, x2, y2) in p.arrow:
        d.line([(x1, y1), (x2, y2)], fill=color, width=width)
        ang, L = math.atan2(y2 - y1, x2 - x1), 4 * width + 6
        tips = [(x2 - L * math.cos(ang + s), y2 - L * math.sin(ang + s)) for s in (-0.45, 0.45)]
        d.polygon([(x2, y2), *tips], fill=color)
        n += 1
    if not n:
        raise EngineError("nothing to draw", hint="give circle, arrow, line or rect")
    return EngineResult(outputs=[Output("result", im, "result.png")],
                        lines=[f"drew {n} shape(s) in {p.color}, {width}px"])


class CensorParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to censor")
    box: list[Box] = Field(min_length=1, description="rectangles to censor; repeatable")
    style: Literal["pixelate", "bar", "blur"] = Field("pixelate", description="pixelate, black bar, or blur")
    block: int = Field(16, ge=1, description="pixel size for pixelate, blur radius for blur")


def censor(p: CensorParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_censor
    im = to_rgb(image)
    for box in p.box:
        x1, y1, x2, y2 = clamp_box(box, im.size)
        region = im.crop((x1, y1, x2, y2))
        w, h = region.size
        if p.style == "bar":
            region = Image.new("RGB", (w, h), "black")
        elif p.style == "blur":
            region = region.filter(ImageFilter.GaussianBlur(p.block))
        else:  # pixelate
            small = region.resize((max(1, w // p.block), max(1, h // p.block)), Image.BILINEAR)
            region = small.resize((w, h), Image.NEAREST)
        im.paste(region, (x1, y1))
    return EngineResult(outputs=[Output("result", im, "result.png")],
                        lines=[f"censored {len(p.box)} region(s), style {p.style}"])


class EyesParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image with the face")
    at: list[Point] = Field(min_length=1, description="eye positions (use find's eye points); repeatable")
    angle: float = Field(155, description="beam direction in degrees, 0 = right, 90 = up")
    size: int | None = Field(None, ge=1, description="beam thickness in px (default: scaled to the image)")
    color: Color = Field("red", description="beam color")


def eyes(p: EyesParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_eyes
    im = to_rgb(image).convert("RGBA")
    W, H = im.size
    size = p.size or max(6, W // 45)
    L = 3 * max(W, H)
    rad = math.radians(p.angle)
    dx, dy = math.cos(rad), -math.sin(rad)
    color = rgb(p.color)
    hot = tuple(min(255, c + (255 - c) * 2 // 3) for c in color)
    layers = [  # (line width, blur radius, fill): wide soft glow, the beam, a hot core
        (3 * size, 2 * size, color + (200,)),
        (size, max(1, size // 3), color + (255,)),
        (max(1, size // 3), 0, hot + (255,)),
    ]
    for width, blur, fill in layers:
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for (x, y) in p.at:
            d.line([(x, y), (x + dx * L, y + dy * L)], fill=fill, width=width)
            r = width * 0.8
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
        if blur:
            layer = layer.filter(ImageFilter.GaussianBlur(blur))
        im = Image.alpha_composite(im, layer)
    # the reference prints argparse's list of lists, and the angle as given (155 default, 30.0 from the CLI)
    return EngineResult(outputs=[Output("result", im.convert("RGB"), "result.png")],
                        lines=[f"laser eyes at {[list(x) for x in p.at]}, angle {p.angle}, size {size}px"])
