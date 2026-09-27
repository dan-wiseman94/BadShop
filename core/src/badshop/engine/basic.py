"""Inspection and working copies."""

from typing import ClassVar

from PIL import Image
from pydantic import Field

from badshop.engine.common import draw_grid, fit, has_alpha, to_rgb
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import ImageRef, Params


class InfoParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to measure")


def info(p: InfoParams, image: Image.Image) -> EngineResult:
    return EngineResult(lines=[f"{p.image}: {image.width}x{image.height}"],
                        data={"width": image.width, "height": image.height})


class PrepParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to make a working copy of")
    max: int = Field(1000, ge=16, description="longest side in px (default 1000)")


def prep(p: PrepParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_prep: same resize, same grid
    im, _ = fit(to_rgb(image), p.max)
    return EngineResult(
        outputs=[Output("work", im, "{stem}_work.png"), Output("grid", draw_grid(im), "{stem}_work_grid.png")],
        lines=[f"size: {im.width}x{im.height}"],
    )


class ViewParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to look at")
    grid: bool = Field(False, description="overlay labeled pixel gridlines for reading coordinates")
    max: int = Field(1024, ge=64, le=4096, description="longest side of the returned view in px")


def view(p: ViewParams, image: Image.Image) -> EngineResult:
    im, scale = fit(image.convert("RGBA") if has_alpha(image) else to_rgb(image), p.max)
    if p.grid:
        im = draw_grid(im)  # on RGBA too: opaque lines and labels, transparent areas stay transparent
    note = "" if scale == 1 else f" (scaled {scale:.3f}; multiply by {1 / scale:.3f} for source pixels)"
    return EngineResult(outputs=[Output("view", im, "{stem}_view.png")], lines=[f"size: {im.width}x{im.height}{note}"])


class ExportParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="finished image to hand to the user")
    name: str | None = Field(None, description="file name without extension")
