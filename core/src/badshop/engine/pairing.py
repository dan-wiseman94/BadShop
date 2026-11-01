"""Compare source/background combinations using explainable geometry and hard-paste previews."""

import math
from pathlib import PurePath
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from pydantic import Field

from badshop.engine.common import clamp_box, font
from badshop.engine.compose import PasteParams, paste
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, ImageRef, Params


class PairImagesParams(Params):
    donors: list[ImageRef] = Field(min_length=1, max_length=6, description="Candidate cutouts or subjects")
    backgrounds: list[ImageRef] = Field(min_length=1, max_length=6, description="Candidate target scenes")
    role: Literal["head", "subject", "object"] = "subject"
    side: Literal["left", "center", "right"] = "center"
    target_box: Box | None = Field(None, description="Optional placement region, in each background's pixels")
    n: int = Field(6, ge=1, le=12, description="How many ranked pair previews to return")


def _faces(image):
    """Bundled detector, no download, no identity/expression/orientation inference."""
    factor = min(1.0, 400 / max(image.size))
    small = image.convert("L").resize((max(1, round(image.width * factor)),
                                        max(1, round(image.height * factor))), Image.Resampling.NEAREST)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if detector.empty():
        return []
    return [tuple(round(int(v) / factor) for v in box)
            for box in detector.detectMultiScale(np.asarray(small), scaleFactor=1.1,
                                                 minNeighbors=4, minSize=(20, 20))]


def _target(image, p, faces):
    if p.target_box is not None:
        return clamp_box(p.target_box, image.size)
    if p.role == "head" and faces:
        x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
        return clamp_box((round(x - w * .15), round(y - h * .3),
                          round(x + w * 1.15), round(y + h * 1.1)), image.size)
    w, h = image.size
    cx = {"left": .25, "center": .5, "right": .75}[p.side]
    half_width = .18 if p.role == "subject" else .13
    top = .24 if p.role == "subject" else .52
    return clamp_box((round(w * (cx - half_width)), round(h * top),
                      round(w * (cx + half_width)), round(h * .94)), image.size)


def _hard_alpha(image):
    rgba = image.convert("RGBA")
    rgba.putalpha(rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
    return rgba


def _preview(base, piece, box):
    # Exactly the existing paste operation, merely at a bounded preview scale.
    factor = min(1.0, 300 / max(base.size))
    base = base.resize((max(1, round(base.width * factor)), max(1, round(base.height * factor))), Image.Resampling.NEAREST)
    scaled_box = tuple(round(v * factor) for v in box)
    if scaled_box[2] <= scaled_box[0] or scaled_box[3] <= scaled_box[1]:
        return base.convert("RGB")
    params = PasteParams(base="background", piece="donor", fit_box=scaled_box)
    return paste(params, base, _hard_alpha(piece)).outputs[0].image


def pair_images(p: PairImagesParams, store) -> EngineResult:
    donors = [(ref, store.load(ref)) for ref in dict.fromkeys(p.donors)]
    backgrounds = [(ref, store.load(ref)) for ref in dict.fromkeys(p.backgrounds)]
    donor_faces = {ref: _faces(im) for ref, im in donors} if p.role == "head" else {}
    rows, warnings = [], []
    for background_ref, background in backgrounds:
        faces = _faces(background)
        try:
            box = _target(background, p, faces)
        except EngineError:
            warnings.append(f"{background_ref}: placement box misses the image")
            continue
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        region = background.crop(box).convert("L")
        region.thumbnail((200, 200), Image.Resampling.NEAREST)
        edges = np.asarray(region.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
        interior = edges[1:-1, 1:-1]
        clutter = float(interior.mean()) / 255 if interior.size else 0
        for donor_ref, donor in donors:
            if donor_ref == background_ref:
                continue
            aspect_error = abs(math.log((donor.width / donor.height) / (bw / bh)))
            scale = max(bw / donor.width, bh / donor.height)
            score = 4 - min(3, aspect_error) - min(2, max(0, scale - 1) * .5) - clutter
            reasons = [f"aspect mismatch {aspect_error:.2f}", f"donor scale {scale:.2f}x"]
            if clutter < .08:
                reasons.append("low-detail placement region")
            if p.role == "head":
                if donor_faces[donor_ref]:
                    area = max(w * h for _, _, w, h in donor_faces[donor_ref]) / (donor.width * donor.height)
                    score += min(1, area * 3)
                    reasons.append(f"donor face occupies {area:.0%} of frame")
                if faces and p.target_box is None:
                    score += .5
                    reasons.append("target uses largest detected face")
            elif faces:
                overlap = sum(max(0, min(x2, x+w)-max(x1, x)) * max(0, min(y2, y+h)-max(y1, y))
                              for x, y, w, h in faces) / (bw * bh)
                score -= min(2, overlap * 3)
                if overlap:
                    reasons.append("placement overlaps an existing face")
            rows.append((score, {"donor": donor_ref, "background": background_ref, "score": round(score, 3),
                "reasons": reasons, "paste_params": {"base": background_ref, "piece": donor_ref,
                                                        "fit_box": list(box)}}, background, donor, box))
    if not rows:
        raise EngineError("no usable image pairs", hint="choose distinct donors and backgrounds with a valid placement box")
    rows.sort(key=lambda row: -row[0])  # stable input order resolves ties
    chosen = rows[:p.n]
    cell, cols = 320, min(3, len(chosen))
    sheet = Image.new("RGB", (cols * cell, math.ceil(len(chosen) / cols) * 350), "#25252b")
    draw = ImageDraw.Draw(sheet)
    label_font = font(14)
    pairs = []
    for i, (_, data, background, donor, box) in enumerate(chosen):
        preview = _preview(background, donor, box)
        x, y = (i % cols) * cell, (i // cols) * 350
        sheet.paste(preview, (x + (cell - preview.width) // 2, y + (300 - preview.height) // 2))
        donor_label = PurePath(data["donor"]).name[:18]
        background_label = PurePath(data["background"]).name[:18]
        draw.text((x+8, y+306), f"{i+1}. Score {data['score']:.2f}", fill="white", font=label_font)
        draw.text((x+8, y+325), f"{donor_label} > {background_label}", fill="white", font=label_font)
        pairs.append({"number": i+1, **data})
    return EngineResult(outputs=[Output("sheet", sheet, "pair_candidates.png")],
        lines=["Pairs ranked by framing, size, available space and detected faces.",
               "Inspect the sheet for pose, expression and meaning; these scores do not understand the joke.",
               "Previews paste the complete donor. Cut out the subject first if needed, then reuse fit_box.", *warnings],
        data={"pairs": pairs, "sources": [None], "warnings": warnings})
