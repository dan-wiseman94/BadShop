"""Pasting cutouts: nearest-neighbor scaling, hard alpha, no blending, ported from reference/badshop.py."""

import random
from typing import ClassVar, Literal

from PIL import Image, ImageOps
from pydantic import Field

from badshop.engine.common import check_size, clamp_box, has_alpha, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, ImageRef, Params, Point, Seed


class PasteParams(Params):
    POSITIONAL: ClassVar = ("base", "piece")
    base: ImageRef = Field(description="image to paste onto")
    piece: ImageRef = Field(description="cutout to paste")
    at: Point | None = Field(None, description="where the anchor goes, pixel coords")
    anchor: Literal["topleft", "center", "bottom"] = Field(
        "topleft", description="which point of the piece `at` refers to (bottom = bottom-center)")
    width: float | None = Field(None, gt=0, le=10_000, description="width to scale the piece to")
    height: float | None = Field(None, gt=0, le=10_000, description="height; omit to keep the aspect ratio")
    fit_box: Box | None = Field(None, description="instead of at/width: scale and center the piece to cover this box")
    scale: float = Field(1.0, gt=0, le=20, description="with fit_box, oversize factor (1.3 = 30% too big)")
    rotate: float = Field(0, description="degrees counter-clockwise")
    flip: bool = Field(False, description="mirror the piece horizontally")
    repeat: int | None = Field(None, ge=1, le=1000, description="scatter this many random copies (0.5-1.5x width) instead")
    region: Box | None = Field(None, description="with repeat, only scatter inside this box")
    seed: Seed = Field(1, description="with repeat, change for a different scatter")


def paste(p: PasteParams, base_im: Image.Image, piece_im: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_paste; its local piece variable `p` is `pc` here, since `p` is the params
    base = to_rgb(base_im).convert("RGBA")
    piece = (piece_im if has_alpha(piece_im) else to_rgb(piece_im)).convert("RGBA")
    if p.flip:
        piece = ImageOps.mirror(piece)
    if not (p.width or p.fit_box):
        raise EngineError("give width (or fit_box)",
                          hint="fit_box covers a box; at + width places by a point")
    if not (p.at or p.fit_box or p.repeat):
        raise EngineError("give at (or fit_box, or repeat)", hint="at is where the anchor point goes")
    if p.repeat and not p.width:  # not in the reference, which crashed here when fit_box stood in for width
        raise EngineError("repeat needs width", hint="each copy is scaled to 0.5-1.5x width")

    def scaled(width, height=None):
        w = max(1, round(width))
        h = max(1, round(height if height else piece.height * w / piece.width))
        check_size(w, h)
        return piece.resize((w, h), Image.NEAREST)

    if p.repeat:
        rng = random.Random(p.seed)
        x1, y1, x2, y2 = clamp_box(p.region, base.size) if p.region else (0, 0, base.width, base.height)
        for _ in range(p.repeat):
            pc = scaled(p.width * rng.uniform(0.5, 1.5))
            if rng.random() < 0.5:
                pc = ImageOps.mirror(pc)
            pc = pc.rotate(rng.uniform(-15, 15), resample=Image.NEAREST, expand=True)
            cx, cy = rng.randint(x1, x2), rng.randint(y1, y2)
            base.paste(pc, (cx - pc.width // 2, cy - pc.height // 2), pc)
        placed = f"{p.repeat} copies scattered over ({x1}, {y1})-({x2}, {y2}), seed {p.seed}"
    else:
        if p.fit_box:
            bx1, by1, bx2, by2 = p.fit_box
            bw, bh = abs(bx2 - bx1), abs(by2 - by1)
            s = max(bw / piece.width, bh / piece.height) * p.scale  # cover the box, then oversize by --scale
            pc = scaled(piece.width * s, piece.height * s)
            if p.rotate:
                pc = pc.rotate(p.rotate, resample=Image.NEAREST, expand=True)
            x, y = min(bx1, bx2) + bw // 2 - pc.width // 2, min(by1, by2) + bh // 2 - pc.height // 2
        else:
            pc = scaled(p.width, p.height)
            if p.rotate:
                pc = pc.rotate(p.rotate, resample=Image.NEAREST, expand=True)
            x, y = p.at
            if p.anchor == "center":
                x, y = x - pc.width // 2, y - pc.height // 2
            elif p.anchor == "bottom":
                x, y = x - pc.width // 2, y - pc.height
        base.paste(pc, (x, y), pc)  # hard alpha: no blending, no shadow, no color match
        placed = f"piece placed with top-left at ({x}, {y}), {pc.width}x{pc.height} after scaling"

    return EngineResult(outputs=[Output("result", base.convert("RGB"), "result.png")],
                        lines=[f"size: {base.width}x{base.height}", placed])
