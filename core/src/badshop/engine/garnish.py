"""Lens flares, clip-art sparkles and fake watermarks, ported from reference/badshop.py."""

import random
from typing import ClassVar, Literal

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from pydantic import Field

from badshop.engine.common import clamp_box, rgb, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.text import load_font
from badshop.engine.types import Box, Color, ImageRef, Params, Point, Seed


class FlareParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to add a lens flare to")
    at: Point = Field(description="where the light is")
    size: int | None = Field(None, ge=2, le=20_000, description="glow radius in px (default: a sixth of the short side)")


def flare(p: FlareParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_flare
    im = to_rgb(image)
    W, H = im.size
    x, y = p.at
    R = p.size or min(W, H) // 6
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
    return EngineResult(outputs=[Output("result", im, "result.png")],
                        lines=[f"lens flare at ({x}, {y}), size {R}px"])


class SparkleParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to sparkle")
    at: list[Point] = Field(default_factory=list, max_length=200, description="sparkle positions; repeatable")
    repeat: int | None = Field(None, ge=1, le=1000, description="scatter this many at random (as well as any `at`)")
    region: Box | None = Field(None, description="with repeat, only scatter inside this box")
    size: int | None = Field(None, ge=2, le=20_000, description="sparkle radius in px (default: scaled to the image)")
    color: Color = Field("#fff27a", description="glow color")
    seed: Seed = Field(1, description="change for a different scatter")


def sparkle(p: SparkleParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_sparkle
    im = to_rgb(image).convert("RGBA")
    W, H = im.size
    rng = random.Random(p.seed)
    size = p.size or max(12, min(W, H) // 18)
    spots = [(x, y, size) for (x, y) in p.at]
    if p.repeat:
        x1, y1, x2, y2 = clamp_box(p.region, im.size) if p.region else (0, 0, W, H)
        spots += [(rng.randint(x1, x2), rng.randint(y1, y2), size * rng.uniform(0.5, 1.4)) for _ in range(p.repeat)]
    if not spots:
        raise EngineError("give at or repeat", hint="at places sparkles, repeat scatters them")
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    stars = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gd, sd = ImageDraw.Draw(glow), ImageDraw.Draw(stars)
    color = rgb(p.color)
    for (x, y, s) in spots:
        g = s * 0.45
        gd.ellipse([x - g, y - g, x + g, y + g], fill=color + (190,))
        k = s * 0.14  # four long points, four pinched waists
        sd.polygon([(x, y - s), (x + k, y - k), (x + s, y), (x + k, y + k),
                    (x, y + s), (x - k, y + k), (x - s, y), (x - k, y - k)], fill=(255, 255, 255, 255))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(size / 5)))
    im = Image.alpha_composite(im, stars)
    return EngineResult(outputs=[Output("result", im.convert("RGB"), "result.png")],
                        lines=[f"{len(spots)} sparkle(s), size about {size}px"])


WATERMARKS = ("hypercam", "bandicam", "ifunny", "mematic")


class WatermarkParams(Params):
    POSITIONAL: ClassVar = ("image", "names")
    image: ImageRef = Field(description="image to watermark")
    names: list[Literal["hypercam", "bandicam", "ifunny", "mematic"]] = Field(
        default_factory=list, max_length=20, description="fake watermarks to add")
    text: str | None = Field(None, max_length=200, description="your own watermark text as well")
    corner: Literal["tl", "tr", "bl", "br"] = Field("br", description="corner for text")


def watermark(p: WatermarkParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_watermark
    im = to_rgb(image).convert("RGBA")
    marks = list(p.names) + (["custom"] if p.text else [])
    if not marks:
        raise EngineError("name a watermark or give text", hint=f"watermarks: {', '.join(WATERMARKS)}")
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
            tw = d.textlength(p.text, font=fnt)
            x = 8 if p.corner[1] == "l" else W - tw - 8
            y = 6 if p.corner[0] == "t" else H - fnt.size * 1.4
            d.text((x, y), p.text, font=fnt, fill=(255, 255, 255, 170), stroke_width=2, stroke_fill=(0, 0, 0, 120))
        im = Image.alpha_composite(im, layer)
    return EngineResult(outputs=[Output("result", im.convert("RGB"), "result.png")],
                        lines=[f"watermarks: {', '.join(marks)}"])
