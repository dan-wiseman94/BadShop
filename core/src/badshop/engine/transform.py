"""Basic deterministic geometry for the manual toolbar."""

from typing import Literal

from PIL import Image, ImageOps
from pydantic import Field

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, ImageRef, Params


class TransformParams(Params):
    image: ImageRef
    crop: Box | None = None
    width: int | None = Field(None, ge=1, le=1000)
    height: int | None = Field(None, ge=1, le=1000)
    rotate: Literal[0, 90, 180, 270] = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


def transform(p: TransformParams, image: Image.Image) -> EngineResult:
    result = image.copy()
    if p.crop is not None:
        x1, y1, x2, y2 = p.crop
        if not (0 <= x1 < x2 <= result.width and 0 <= y1 < y2 <= result.height):
            raise EngineError("crop must be a nonempty rectangle inside the image")
        result = result.crop(p.crop)
    if p.width or p.height:
        width = p.width or max(1, round(result.width * p.height / result.height))
        height = p.height or max(1, round(result.height * p.width / result.width))
        if max(width, height) > 1000:
            raise EngineError("resized working images must fit within 1000 pixels")
        result = result.resize((width, height), Image.Resampling.NEAREST)
    if p.flip_horizontal:
        result = ImageOps.mirror(result)
    if p.flip_vertical:
        result = ImageOps.flip(result)
    if p.rotate:
        result = result.rotate(p.rotate, resample=Image.Resampling.NEAREST, expand=True)
    return EngineResult(outputs=[Output("result", result, "result.png")])
