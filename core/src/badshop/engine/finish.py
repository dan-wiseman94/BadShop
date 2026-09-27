"""Finishing: crunchy JPEGs, dithered GIFs, deep-frying and animated GIFs, ported from reference/badshop.py."""

import random
from typing import ClassVar, Literal

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
from pydantic import Field

from badshop.engine.common import jpeg_cycle, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import FileName, ImageRef, Params, Point


class SaveParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="finished image")
    quality: int = Field(35, ge=1, le=95, description="JPEG quality")
    passes: int = Field(1, ge=1, le=20, description="recompress this many times for more artifacts")
    lowres: float | None = Field(None, gt=0, le=1, description="downscale to this fraction and back up (0.3 = potato)")
    gif: bool = Field(False, description="write a dithered 1999-style GIF instead of a JPEG")
    colors: int = Field(64, ge=2, le=256, description="with gif, palette size")
    name: FileName | None = Field(None, description="file name without extension")


def save(p: SaveParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_save
    im = to_rgb(image)
    if p.lowres and p.lowres < 1:
        w, h = im.size
        im = im.resize((max(1, int(w * p.lowres)), max(1, int(h * p.lowres))), Image.BILINEAR)
        im = im.resize((w, h), Image.NEAREST)
    for _ in range(max(0, p.passes - 1)):  # recompress for extra artifacts
        im = jpeg_cycle(im, p.quality)
    hint = f"final:{p.name}" if p.name else "final:{stem}"
    if p.gif:
        out = Output("saved", im.quantize(colors=p.colors, dither=Image.Dither.FLOYDSTEINBERG), hint, fmt="GIF")
        return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}, gif with {p.colors} colors, dithered"])
    out = Output("saved", im, hint, fmt="JPEG", quality=p.quality)
    return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}, jpeg quality {p.quality}, {p.passes} pass(es)"])


def deepfry(im, level, tint=True, seed=1) -> tuple[Image.Image, int]:
    """The deep-fried meme look, scaled by level 1 (lightly toasted) to 5 (nuked)."""
    # reference/badshop.py deepfry; the grain is seeded (the one intended pixel change)
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

    import numpy as np
    w, h = im.size
    rng = np.random.default_rng(seed % 2**64)  # numpy rejects negative seeds; folding keeps any int repeatable
    grain = rng.normal(128.0, lerp(6, 34), size=(h, w)).clip(0, 255).astype(np.uint8)
    noise = Image.fromarray(grain, "L").convert("RGB")  # same gaussian grain, now reproducible
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


class DeepfryParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to deep-fry")
    level: int = Field(3, ge=1, le=5, description="1 = lightly toasted, 3 = default, 5 = nuked")
    no_tint: bool = Field(False, description="skip the red/yellow color cast")
    seed: int = Field(1, description="grain pattern; same seed, same result")
    name: FileName | None = Field(None, description="file name without extension")


def deepfry_tool(p: DeepfryParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_deepfry
    im, quality = deepfry(to_rgb(image), p.level, tint=not p.no_tint, seed=p.seed)
    hint = f"final:{p.name}" if p.name else "final:{stem}_deepfried"
    return EngineResult(outputs=[Output("deepfried", im, hint, fmt="JPEG", quality=quality)],
                        lines=[f"size: {im.width}x{im.height}, level {p.level}"])


class AnimateParams(Params):
    POSITIONAL: ClassVar = ("images",)
    images: list[ImageRef] = Field(min_length=1, max_length=32, description="frames cycle through these (e.g. with and without laser eyes)")
    effect: Literal["none", "shake", "flash", "zoom", "spin"] = Field("none", description="motion effect")
    frames: int | None = Field(None, ge=1, le=120, description="frame count (default depends on the effect)")
    delay: int = Field(80, ge=10, le=10_000, description="ms per frame")
    amount: float | None = Field(None, gt=0, le=100, description="shake: max px offset; zoom: final zoom factor (default 3)")
    at: Point | None = Field(None, description="zoom target (default: the center)")
    hold: int = Field(6, ge=0, le=100, description="zoom: repeat the last frame this many times")
    fry: int | None = Field(None, ge=1, le=5, description="deep-fry every frame at this level (zoom ramps up to it)")
    colors: int = Field(128, ge=2, le=256, description="palette size per frame")
    seed: int = Field(1, description="picks the shake pattern and the fry grain; same seed, same result")
    name: FileName | None = Field(None, description="file name without extension")


def animate(p: AnimateParams, images: list[Image.Image]) -> EngineResult:
    # reference/badshop.py cmd_animate
    sources = [to_rgb(i) for i in images]
    size = sources[0].size
    sources = [s if s.size == size else s.resize(size, Image.NEAREST) for s in sources]
    W, H = size
    n = p.frames or {"none": len(sources), "shake": 8, "flash": 6, "zoom": 14, "spin": 12}[p.effect]
    n = max(n, len(sources))
    if p.effect == "zoom" and n > 1 and (p.amount or 3.0) < 1:  # zooming out crashes the reference's crop
        raise EngineError(f"zoom amount {p.amount} is below 1",
                          hint="amount is the final zoom factor (3 = 3x); zoom only zooms in")
    rng = random.Random(p.seed)
    cx, cy = p.at or (W // 2, H // 2)
    frames = []
    for k in range(n):
        f = sources[k % len(sources)]
        t = k / max(1, n - 1)
        if p.effect == "shake":
            amp = int(p.amount or max(4, W // 50))
            f = ImageChops.offset(f, rng.randint(-amp, amp), rng.randint(-amp, amp))
        elif p.effect == "flash" and k % 2:
            f = ImageOps.invert(f)
        elif p.effect == "zoom":
            z = 1 + t * ((p.amount or 3.0) - 1)
            zw, zh = W / z, H / z
            x0 = min(max(0, cx - zw / 2), W - zw)
            y0 = min(max(0, cy - zh / 2), H - zh)
            f = f.resize(size, Image.NEAREST, box=(x0, y0, x0 + zw, y0 + zh))
        elif p.effect == "spin":
            f = f.rotate(-360 * k / n, resample=Image.NEAREST, fillcolor=(0, 0, 0))
        if p.fry:  # zoom ramps the frying up as it closes in; everything else fries at a constant level
            # seed + k: identically fried frames would be merged by the GIF writer
            f, _ = deepfry(f, 1 + round(t * (p.fry - 1)) if p.effect == "zoom" else p.fry, seed=p.seed + k)
        frames.append(f.quantize(colors=p.colors, dither=Image.Dither.FLOYDSTEINBERG))
    if p.effect == "zoom" and p.hold:
        frames += [frames[-1]] * p.hold
    hint = f"final:{p.name}" if p.name else f"final:{{stem}}_{p.effect}"
    out = Output("animated", frames[0], hint, fmt="GIF", frames=frames, duration=p.delay)
    return EngineResult(outputs=[out], lines=[f"size: {W}x{H}, {len(frames)} frames at {p.delay}ms, effect {p.effect}"
                                              + (f", fried to level {p.fry}" if p.fry else "")])
