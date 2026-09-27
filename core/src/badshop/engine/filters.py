"""The Filters menu and bulge/pinch warps, ported from reference/badshop.py."""

from typing import ClassVar, Literal

from PIL import Image, ImageFilter, ImageOps
from pydantic import Field

from badshop.engine.common import need_cv2, to_rgb
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import ImageRef, Params, Spot

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

FilterName = Literal["blur", "contour", "edges", "emboss", "grayscale", "invert", "oilpaint",
                     "posterize", "sepia", "sharpen", "solarize"]


class FilterParams(Params):
    POSITIONAL: ClassVar = ("image", "names")
    image: ImageRef = Field(description="image to filter")
    names: list[FilterName] = Field(min_length=1, description="filters to apply, in order")


def apply_filters(p: FilterParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_filter
    im = to_rgb(image)
    for name in p.names:
        im = FILTERS[name](im)
    return EngineResult(outputs=[Output("result", im, "result.png")], lines=[f"applied: {', '.join(p.names)}"])


class WarpParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to warp")
    at: list[Spot] = Field(min_length=1, description="spots as X Y R (center and radius); repeatable")
    strength: float = Field(0.6, description="positive bulges, negative pinches (1.0 is huge, -0.5 strong pinch)")


def warp(p: WarpParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_warp
    cv2, np = need_cv2()
    arr = np.array(to_rgb(image))
    H, W = arr.shape[:2]
    ys, xs = np.indices((H, W), dtype=np.float32)
    for (cx, cy, r) in p.at:
        dx, dy = xs - cx, ys - cy
        d = np.sqrt(dx * dx + dy * dy) / max(1, r)
        # sample from d**strength of the way out: >0 magnifies the middle (bulge), <0 shrinks it (pinch)
        f = np.where(d < 1, np.power(np.maximum(d, 1e-3), p.strength), 1.0).astype(np.float32)
        arr = cv2.remap(arr, cx + dx * f, cy + dy * f, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
    # the reference prints the strength as argparse's float (0.8, -0.5, 1.0)
    return EngineResult(outputs=[Output("result", Image.fromarray(arr), "result.png")],
                        lines=[f"{'bulged' if p.strength > 0 else 'pinched'} {len(p.at)} spot(s), "
                               f"strength {p.strength}"])
