"""Cutouts: a box with its background knocked out, a hard oval, or a plain rectangle, ported from
reference/badshop.py."""

from typing import ClassVar, Literal

from PIL import Image, ImageDraw, ImageFilter
from pydantic import Field

from badshop.engine import assets
from badshop.engine.common import clamp_box, has_alpha, rgb, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, Color, ImageRef, Params

# Model -> weights licence -> upstream source (checked 2026-09-26; rembg's own code is MIT):
#   u2net            -> Apache-2.0 -> https://github.com/xuebinqin/U-2-Net
#   u2net_human_seg  -> Apache-2.0 -> https://github.com/xuebinqin/U-2-Net
#   isnet-anime      -> Apache-2.0 -> https://github.com/SkyTNT/anime-segmentation
#   birefnet-general -> MIT        -> https://github.com/ZhengPeng7/BiRefNet
# Never rembg's own default, bria-rmbg (BRIA licence: commercial use needs a paid agreement).
RembgModel = Literal["u2net", "u2net_human_seg", "isnet-anime", "birefnet-general"]


def dilate(alpha, n):
    """Grow a hard mask by n px with a round brush (square if OpenCV is missing)."""
    try:
        import cv2
        import numpy as np
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * n + 1, 2 * n + 1))
        return Image.fromarray(cv2.dilate(np.array(alpha), k))
    except ImportError:
        return alpha.filter(ImageFilter.MaxFilter(2 * n + 1))


class CutoutParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to cut from")
    box: Box | None = Field(None, description="rectangle to cut, pixel coords; omit to use the whole image")
    model: RembgModel = Field("u2net", description="background remover: u2net (default, fast), "
                              "u2net_human_seg (people), isnet-anime (cartoons), birefnet-general (cleaner)")
    threshold: int = Field(128, ge=0, le=255, description="alpha cutoff 0-255")
    grow: int = Field(0, ge=0, description="dilate the mask N px to drag in a halo of old background")
    no_ai: bool = Field(False, description="skip background removal; keep the whole rectangle")
    oval: bool = Field(False, description="cut a hard-edged ellipse filling the box instead (face-only swap)")
    sticker: int | None = Field(None, ge=1, description="add an N px flat outline around the shape")
    sticker_color: Color = Field("white", description="outline color for sticker")


def cutout(p: CutoutParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_cutout; the store already loads images upright
    src = image
    im = src.convert("RGBA") if has_alpha(src) else to_rgb(src)
    box = clamp_box(p.box, im.size) if p.box else (0, 0, im.width, im.height)
    piece = im.crop(box)

    if p.oval:  # the 2010 face-swap-app look: a hard-edged ellipse, no background removal
        alpha = Image.new("L", piece.size, 0)
        ImageDraw.Draw(alpha).ellipse([0, 0, piece.width - 1, piece.height - 1], fill=255)
        piece = piece.convert("RGBA")
        piece.putalpha(alpha)
    elif p.no_ai:
        piece = piece.convert("RGBA")
    else:
        try:
            assets.configure_rembg()
            from rembg import new_session, remove
        except ImportError:
            raise EngineError("rembg is not installed",
                              hint='pip install "rembg[cpu]", or use no_ai') from None
        try:
            session = new_session(p.model)
        except OSError as e:  # requests' errors are OSErrors: offline, or the first-run model download failed
            raise EngineError(f"couldn't download the {p.model} background-removal model ({e})",
                              hint="check the internet connection; it is only downloaded once, "
                                   "or use no_ai") from None
        mask = remove(piece.convert("RGB"), session=session).getchannel("A")
        alpha = mask.point(lambda v: 255 if v >= p.threshold else 0)
        if p.grow:
            alpha = alpha.filter(ImageFilter.MaxFilter(2 * p.grow + 1))
        piece = piece.convert("RGBA")  # keep the original pixels, so a grown mask shows real old background
        piece.putalpha(alpha)

    opaque = piece.getbbox()
    if opaque is None:
        raise EngineError("nothing was kept: the background remover found no subject in that box",
                          hint="try a bigger box, a different model, or no_ai")
    piece = piece.crop(opaque)
    hist = piece.getchannel("A").histogram()
    coverage = sum(hist[1:]) / (piece.width * piece.height)

    if p.sticker:  # thick flat outline behind the shape, like a sticker-pack cutout
        n = p.sticker
        padded = Image.new("RGBA", (piece.width + 2 * n + 2, piece.height + 2 * n + 2), (0, 0, 0, 0))
        padded.paste(piece, (n + 1, n + 1))
        hard = padded.getchannel("A").point(lambda v: 255 if v else 0)
        backing = Image.new("RGBA", padded.size, rgb(p.sticker_color) + (255,))
        backing.putalpha(dilate(hard, n))
        piece = Image.alpha_composite(backing, padded)

    lines = [f"size: {piece.width}x{piece.height}", f"opaque: {coverage:.0%} of the cutout's bounding box"]
    if coverage < 0.15:
        lines.append("warning: very little was kept; the box may have missed the subject")
    return EngineResult(outputs=[Output("cutout", piece, "{stem}_cutout.png")], lines=lines,
                        data={"coverage": coverage})
