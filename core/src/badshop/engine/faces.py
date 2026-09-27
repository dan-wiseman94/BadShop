"""Face finding: YuNet with five landmarks, Haar cascades as the fallback and for cats, ported from
reference/badshop.py."""

import math
from typing import ClassVar, Literal

from PIL import Image, ImageDraw
from pydantic import Field

from badshop.engine import assets
from badshop.engine.common import font, int_box, label, need_cv2, overlap, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import ImageRef, Params

YUNET = assets.Pinned(  # opencv_zoo commit f12e127 ("update yunet to v2"), the file's latest version
    "https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", size=232589)


def _plausible(r, W, H) -> bool:
    """YuNet sometimes returns junk rows (inf, nan, 1e32, a box off the image), mostly on tiny or blank
    images; the reference crashed drawing them. A real face has a size, and its box and landmarks lie
    on or near the image: inside it grown by its own size on every side."""
    if not all(math.isfinite(v) for v in r[:15]) or r[2] <= 0 or r[3] <= 0:
        return False
    xs, ys = [r[0], r[0] + r[2], *r[4:14:2]], [r[1], r[1] + r[3], *r[5:14:2]]
    return all(-W <= v <= 2 * W for v in xs) and all(-H <= v <= 2 * H for v in ys)


def yunet_faces(cv2, bgr, min_score):
    """Faces with five landmarks each, from OpenCV's small YuNet CNN."""
    model = assets.cached("face_detection_yunet_2023mar.onnx", YUNET.url, sha256=YUNET.sha256, size=YUNET.size)
    H, W = bgr.shape[:2]
    det = cv2.FaceDetectorYN.create(str(model), "", (W, H), min_score, 0.3, 5000)
    _, rows = det.detect(bgr)

    def point(px, py):  # rounded, and never further out than _plausible allows (the chin is extrapolated)
        return min(max(round(px), -W), 2 * W), min(max(round(py), -H), 2 * H)

    faces = []
    for r in ([] if rows is None else rows.tolist()):
        if not _plausible(r, W, H):
            continue
        x, y, w, h = r[:4]
        eyes = sorted([(r[4], r[5]), (r[6], r[7])])  # left to right in the image
        mouth = sorted([(r[10], r[11]), (r[12], r[13])])
        ec = ((eyes[0][0] + eyes[1][0]) / 2, (eyes[0][1] + eyes[1][1]) / 2)
        mc = ((mouth[0][0] + mouth[1][0]) / 2, (mouth[0][1] + mouth[1][1]) / 2)
        em = max(1.0, math.dist(ec, mc))  # eyes-to-mouth distance: the unit for everything below
        ed = max(1.0, math.dist(*eyes))
        ux, uy = (mc[0] - ec[0]) / em, (mc[1] - ec[1]) / em  # down the face, even when it's tilted
        chin = (mc[0] + ux * 0.7 * em, mc[1] + uy * 0.7 * em)
        top, bottom = ec[1] - 2.5 * em, chin[1] + 0.3 * em  # hair above, a strip of neck below
        cx = (ec[0] + chin[0]) / 2
        half = max(0.45 * (bottom - top), 1.6 * ed)
        face = {
            "kind": "face", "score": r[14],
            "box": int_box((x, y, x + w, y + h), W, H),
            "head": int_box((cx - half, top, cx + half, bottom), W, H),
            "oval": int_box((cx - 1.15 * ed, ec[1] - 0.75 * em, cx + 1.15 * ed, chin[1]), W, H),
            "eyes": [point(*e) for e in eyes], "estimated": False,
            "nose": point(r[8], r[9]),
            "mouth": [point(*m) for m in mouth],
            "chin": point(*chin),
            "roll": math.degrees(math.atan2(eyes[1][1] - eyes[0][1], eyes[1][0] - eyes[0][0])),
        }
        # a box clamped to nothing (x2 < x1 or y2 < y1) lies off the image: junk, not a face
        if all(b[2] >= b[0] and b[3] >= b[1] for b in (face["box"], face["head"], face["oval"])):
            faces.append(face)
    return faces


def haar_faces(cv2, gray, kind):
    """Older, rougher cascade detector: the fallback for faces, and the only option for cats."""
    H, W = gray.shape[:2]
    minsize = (max(20, min(W, H) // 20),) * 2

    def detect(name, img, scale=1.1, neighbors=5):
        c = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        return [tuple(int(v) for v in r) for r in c.detectMultiScale(img, scale, neighbors, minSize=minsize)]

    boxes = []
    if kind == "face":
        boxes += detect("haarcascade_frontalface_default.xml", gray)
        boxes += detect("haarcascade_profileface.xml", gray)
        boxes += [(W - x - w, y, w, h) for (x, y, w, h) in detect("haarcascade_profileface.xml", cv2.flip(gray, 1))]
    else:
        boxes += detect("haarcascade_frontalcatface_extended.xml", gray, 1.05, 3)

    eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    faces = []
    for (x, y, w, h) in boxes:
        roi = gray[y:y + int(h * 0.65), x:x + w]
        eyes = eye_cascade.detectMultiScale(roi, 1.1, 5, minSize=(max(8, w // 10),) * 2)
        eyes = sorted(eyes, key=lambda e: -e[2] * e[3])[:2]
        centers = sorted((x + ex + ew // 2, y + ey + eh // 2) for (ex, ey, ew, eh) in eyes)
        estimated = len(centers) != 2
        if estimated:
            centers = [(x + int(w * 0.3), y + int(h * 0.4)), (x + int(w * 0.7), y + int(h * 0.4))]
        faces.append({
            "kind": kind, "score": None, "box": (x, y, x + w, y + h),
            "head": int_box((x - w / 4, y - h * 0.45, x + w * 1.25, y + h * 1.15), W, H),
            "oval": int_box((x + w * 0.12, y + h * 0.1, x + w * 0.88, y + h), W, H),
            "eyes": centers, "estimated": estimated,
        })
    return faces


def _jsonable(face: dict) -> dict:
    def conv(v):
        if hasattr(v, "item"):  # numpy scalars (Haar eye centres are numpy ints)
            return v.item()
        if isinstance(v, (tuple, list)):
            return [conv(x) for x in v]
        return float(v) if isinstance(v, float) else v
    return {k: conv(v) for k, v in face.items()}


class FindParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to search")
    what: Literal["faces", "cats", "all"] = Field("faces", description="faces (human), cats, or all")
    detector: Literal["auto", "yunet", "haar"] = Field(
        "auto", description="auto: YuNet with landmarks, falling back to Haar cascades")
    min_score: float = Field(0.7, ge=0, le=1, description="YuNet confidence cutoff (lower finds more, and more junk)")


def find(p: FindParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_find; every print goes to `lines` in the same order
    cv2, np = need_cv2()
    im = to_rgb(image)
    W, H = im.size
    arr = np.array(im)
    gray = cv2.equalizeHist(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY))
    lines = []

    found = []
    if p.what in ("faces", "all"):
        detector = p.detector
        if detector in ("auto", "yunet"):
            try:
                found += yunet_faces(cv2, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), p.min_score)
            except Exception as e:
                if detector == "yunet":
                    raise EngineError(f"YuNet failed: {e}", hint="use detector=haar") from e
                # assets.cached wraps the network error; show the original, as the reference does
                lines.append(f"note: YuNet unavailable ({e.__cause__ or e}); "
                             "using Haar cascades, whose eye points are rougher")
                detector = "haar"
        if detector == "haar":
            found += haar_faces(cv2, gray, "face")
    if p.what in ("cats", "all"):
        found += haar_faces(cv2, gray, "cat")

    def area(f):
        b = f["box"]
        return (b[2] - b[0]) * (b[3] - b[1])

    kept = []
    for f in sorted(found, key=lambda f: -area(f)):
        if all(overlap(f["box"], k["box"]) < 0.4 for k in kept):
            kept.append(f)
    kept.sort(key=lambda f: f["box"][0])  # left to right, so numbering is stable
    if not kept:
        return EngineResult(lines=lines + [f"nothing found in {p.image}; pick the box from the grid instead"],
                            data={"faces": []})

    annotated = im.copy()
    d = ImageDraw.Draw(annotated)
    fnt = font(max(14, min(W, H) // 30))

    def dot(pt, color, r=4):
        d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=color)

    for i, f in enumerate(kept, 1):
        x1, y1, x2, y2 = f["box"]
        score = f" score {f['score']:.2f}" if f["score"] is not None else ""
        lines.append(f"{f['kind']} {i}: box {x1} {y1} {x2} {y2} ({x2 - x1}x{y2 - y1}){score}")
        lines.append(f"head {i}: box {' '.join(map(str, f['head']))}   <- hair to neck; use for cutout and --fit-box")
        lines.append(f"oval {i}: box {' '.join(map(str, f['oval']))}   "
                     "<- brows to chin; `cutout --oval --box` for a face-only swap")
        (ex1, ey1), (ex2, ey2) = f["eyes"]
        lines.append(f"eyes {i}{' (estimated)' if f['estimated'] else ''}: {ex1} {ey1} {ex2} {ey2}")
        if "nose" in f:
            (mx1, my1), (mx2, my2) = f["mouth"]
            lines.append(f"nose {i}: {f['nose'][0]} {f['nose'][1]}")
            lines.append(f"mouth {i}: {mx1} {my1} {mx2} {my2}   (corners)")
            lines.append(f"chin {i}: {f['chin'][0]} {f['chin'][1]}")
            lines.append(f"roll {i}: {f['roll']:+.1f} deg   "
                         "(clockwise tilt; paste --rotate <piece roll - target roll> to match)")
        d.rectangle(f["box"], outline=(255, 0, 0), width=2)
        d.rectangle(f["head"], outline=(255, 0, 255), width=2)
        d.ellipse(f["oval"], outline=(0, 255, 255), width=2)
        for pt in f["eyes"]:
            dot(pt, (0, 255, 0))
        if "nose" in f:
            for pt in (f["nose"], *f["mouth"]):
                dot(pt, (255, 255, 0), 3)
            dot(f["chin"], (255, 140, 0))
        label(d, (f["head"][0] + 4, f["head"][1] + 4), str(i), fnt)
    legend = ("  (red = face, magenta = head, cyan = oval, green = eyes, "
              "yellow = nose/mouth, orange = chin)")
    return EngineResult(outputs=[Output("annotated", annotated, "{stem}_faces.png", caption=legend)],
                        lines=lines, data={"faces": [_jsonable(f) for f in kept]})
