"""Portable asset packs: bounded ZIPs, hashed image bytes, and library metadata.

Archive members are read by exact hash names, never extracted to arbitrary filesystem paths.
All content is validated before any library entry is installed.
"""

import hashlib
import io
import json
import math
import os
import stat
import time
import uuid
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import ValidationError

from badshop.engine.common import font
from badshop.engine.errors import EngineError
from badshop.session.artifacts import ArtifactStore
from badshop.session.library import AssetDetails, AssetLibrary, LibraryEntry
from badshop.session.models import Source
from badshop.session.session import Session

MAX_PACK = 80 * 2**20
MAX_ENTRY = 20 * 2**20
MAX_ITEMS = 100
BUILTINS = {
    "school-lab": ("School computer lab", "Gold stars, certificates, pointing arrows and A+ badges",
                   ["GOLD STAR", "A+", "GOOD JOB", "LOOK HERE"]),
    "homepage-1998": ("1998 personal homepage", "Under-construction sign, visitor counter, web ring and email badge",
                      ["UNDER CONSTRUCTION", "VISITORS 000042", "WEB RING", "EMAIL ME"]),
    "supermarket": ("Discount supermarket", "Sale bursts, coupons and questionable special offers",
                    ["SALE!", "ONLY 99c", "BUY 1 GET 7", "MANAGER SPECIAL"]),
    "conspiracy": ("Cheap conspiracy documentary", "Evidence cards, red string, classified stamp and question marker",
                   ["EVIDENCE A", "CLASSIFIED", "COINCIDENCE?", "FOLLOW THE STRING"]),
    "gaming-magazine": ("Bootleg gaming magazine", "Review badges, controller icon, screenshot label and bonus stamp",
                        ["11/10", "PRO GAMER", "EXCLUSIVE!", "BONUS LEVEL"]),
    "local-cable": ("Local cable TV", "Live lower third, test pattern, station bug and rabbit-ear television",
                    ["LIVE", "PLEASE STAND BY", "CH 04", "LOCAL ACCESS"]),
    "bargain-packaging": ("Bargain-store packaging", "Nutrition panel, hanging price tag, prize burst and value-size bag",
                          ["NUTRITION FACTS", "CLEARANCE", "FREE PRIZE", "VALUE SIZE"]),
    "office-bureaucracy": ("Office bureaucracy", "Rejected rubber stamp, manila folder, clipped memo and stapler",
                           ["REJECTED", "PENDING", "MEMO", "FILE THIS"]),
}


def listing():
    return [{"id": key, "name": value[0], "description": value[1], "count": len(value[2])}
            for key, value in BUILTINS.items()]


def _label(draw, text, box, color, size=34):
    x1, y1, x2, y2 = box
    for pixels in range(size, 8, -2):
        face = font(pixels)
        bounds = draw.textbbox((0, 0), text, font=face)
        if bounds[2] - bounds[0] <= x2 - x1 and bounds[3] - bounds[1] <= y2 - y1:
            break
    draw.text(((x1 + x2) // 2, (y1 + y2) // 2), text, font=face, fill=color, anchor="mm")


def _broadcast_sticker(index, label):
    im = Image.new("RGBA", (320, 180))
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    if index == 0:
        d.polygon([(10, 70), (278, 70), (310, 130), (10, 130)], fill="#001e70")
        d.rectangle((10, 43, 113, 70), fill="#ffdc00")
        d.ellipse((25, 86, 51, 112), fill="#ff2424")
        _label(d, label, (65, 78, 265, 123), "white", 40)
        d.rectangle((10, 132, 310, 143), fill="#ffdc00")
    elif index == 1:
        colors = ["#d0d0d0", "#ffff00", "#00ffff", "#00dd00", "#ff00ff", "#ff0000", "#0000ff"]
        for i, color in enumerate(colors):
            d.rectangle((13 + i * 42, 16, 54 + i * 42, 119), fill=color)
        d.rectangle((13, 120, 306, 164), fill="black")
        _label(d, label, (20, 125, 299, 158), "white", 25)
    elif index == 2:
        d.ellipse((83, 3, 237, 157), fill="#132373", outline="white", width=6)
        d.rectangle((61, 61, 259, 123), fill="#ffdf00", outline="#132373", width=5)
        _label(d, label, (75, 69, 245, 115), "#132373", 42)
    else:
        d.line([(103, 4), (160, 46), (219, 4)], fill="#303030", width=6)
        d.rectangle((35, 44, 285, 158), fill="#70402b", outline="#1b1511", width=5)
        d.rectangle((49, 57, 242, 144), fill="#00d8bf", outline="black", width=4)
        d.ellipse((255, 68, 272, 85), fill="#eeeecc", outline="black", width=2)
        d.ellipse((255, 108, 272, 125), fill="#eeeecc", outline="black", width=2)
        d.rectangle((52, 158, 69, 173), fill="#1b1511")
        d.rectangle((252, 158, 269, 173), fill="#1b1511")
        _label(d, label, (57, 83, 234, 118), "#102424", 25)
    return im


def _packaging_sticker(index, label):
    im = Image.new("RGBA", (320, 180))
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    if index == 0:
        d.rectangle((45, 8, 275, 172), fill="white", outline="black", width=5)
        _label(d, label, (52, 13, 268, 47), "black", 24)
        d.rectangle((52, 51, 268, 59), fill="black")
        for y in range(80, 160, 25):
            d.line((54, y, 266, y), fill="black", width=2)
        _label(d, "100% QUESTIONABLE", (54, 60, 266, 80), "black", 15)
    elif index == 1:
        d.polygon([(42, 45), (112, 8), (278, 45), (278, 168), (42, 168)], fill="#ffff40", outline="#b62016", width=4)
        d.ellipse((101, 25, 119, 43), fill=(0, 0, 0, 0), outline="#b62016", width=3)
        _label(d, label, (55, 65, 265, 105), "#b62016", 30)
        _label(d, "WAS TOO MUCH", (55, 120, 265, 147), "#1b1712", 19)
    elif index == 2:
        points = [(160 + math.cos(i * math.pi / 10) * (151 if i % 2 == 0 else 105),
                   90 + math.sin(i * math.pi / 10) * (84 if i % 2 == 0 else 56)) for i in range(20)]
        d.polygon(points, fill="#e52a96", outline="#252092", width=5)
        _label(d, label, (45, 65, 275, 115), "white", 33)
    else:
        d.polygon([(65, 12), (255, 12), (276, 168), (44, 168)], fill="#4a9cdd", outline="#162f6a", width=4)
        for x in range(70, 250, 14):
            d.line((x, 14, x, 29), fill="#162f6a", width=3)
            d.line((x, 152, x, 166), fill="#162f6a", width=3)
        d.ellipse((76, 45, 244, 139), fill="#ffffc0", outline="#162f6a", width=3)
        _label(d, label, (86, 68, 234, 112), "#162f6a", 31)
    return im


def _office_sticker(index, label):
    im = Image.new("RGBA", (320, 180))
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    if index == 0:
        d.rectangle((136, 11, 184, 68), fill="#303030", outline="black", width=3)
        d.ellipse((125, 3, 195, 33), fill="#303030", outline="black", width=3)
        d.rectangle((34, 62, 286, 163), fill="#ffe7db", outline="#bb1717", width=7)
        d.rectangle((45, 73, 275, 152), outline="#bb1717", width=3)
        _label(d, label, (55, 87, 265, 136), "#bb1717", 38)
    elif index == 1:
        d.polygon([(19, 45), (19, 18), (130, 18), (151, 45), (301, 45), (301, 164), (19, 164)],
                  fill="#d9a940", outline="#704b19", width=4)
        d.polygon([(11, 65), (309, 65), (288, 166), (32, 166)], fill="#f4cb6c", outline="#704b19", width=4)
        _label(d, label, (58, 91, 262, 139), "#553c22", 35)
    elif index == 2:
        d.rectangle((69, 13, 252, 172), fill="#fffce7", outline="#354457", width=3)
        d.line([(88, 46), (88, 5), (113, 5), (113, 53), (97, 53), (97, 16)], fill="#d42a2a", width=5)
        _label(d, label, (126, 28, 238, 66), "#354457", 27)
        for y in range(87, 157, 22):
            d.line((87, y, 235, y), fill="#354457", width=2)
    else:
        d.rectangle((26, 132, 294, 160), fill="#555555", outline="black", width=4)
        d.polygon([(31, 126), (63, 56), (273, 94), (283, 125)], fill="#bb222c", outline="#3b1010", width=5)
        d.rectangle((39, 121, 277, 134), fill="#cecece", outline="#444444", width=3)
        _label(d, label, (94, 74, 250, 112), "white", 22)
    return im


def _sticker(pack_id, index, label):
    themed = {"local-cable": _broadcast_sticker, "bargain-packaging": _packaging_sticker,
              "office-bureaucracy": _office_sticker}
    if pack_id in themed:
        return themed[pack_id](index, label)
    im = Image.new("RGBA", (320, 180))
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    if pack_id == "school-lab" and index == 0:
        points = [(160 + math.sin(i * math.pi / 5) * (85 if i % 2 == 0 else 38),
                   90 - math.cos(i * math.pi / 5) * (85 if i % 2 == 0 else 38)) for i in range(10)]
        d.polygon(points, fill="#ffe138", outline="#8a4b00", width=4)
        label = "STAR"
    elif pack_id == "supermarket":
        points = [(160 + math.cos(i * math.pi / 12) * (157 if i % 2 == 0 else 125),
                   90 + math.sin(i * math.pi / 12) * (87 if i % 2 == 0 else 65)) for i in range(24)]
        d.polygon(points, fill="#ffff00", outline="#d00000", width=5)
    elif pack_id == "conspiracy" and index == 3:
        d.line([(8, 140), (70, 45), (160, 125), (245, 25), (310, 110)], fill="#e90000", width=8)
        for x, y in [(8, 140), (160, 125), (310, 110)]:
            d.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#a90000")
        return im
    elif pack_id == "school-lab" and index == 3:
        d.polygon([(5, 55), (210, 55), (210, 10), (315, 90), (210, 170), (210, 125), (5, 125)], fill="#e30024")
    else:
        palette = {"school-lab": ("#ffdf35", "#0000aa"), "homepage-1998": ("#000080", "#ffff00"),
                   "conspiracy": ("#f4edce", "#bb0000"), "gaming-magazine": ("#431c68", "#00ff88")}
        bg, edge = palette.get(pack_id, ("#ffff00", "#000000"))
        d.rectangle((8, 22, 312, 158), fill=bg, outline=edge, width=7)
        if pack_id == "homepage-1998" and index == 0:
            for x in range(10, 310, 30):
                d.rectangle((x, 24, x + 15, 42), fill="#ffff00")
                d.rectangle((x, 138, x + 15, 156), fill="#ffff00")
        if pack_id == "gaming-magazine" and index == 1:
            d.rectangle((35, 66, 85, 116), fill="black")
            d.rectangle((54, 48, 67, 135), fill="black")
            d.ellipse((245, 50, 273, 78), fill="#ff2255")
            d.ellipse((268, 90, 296, 118), fill="#22ccff")
            label = "PLAYER 1"
    ink = "white" if pack_id in ("homepage-1998", "gaming-magazine") or (pack_id == "school-lab" and index == 3) else "#111111"
    for size in range(36, 10, -2):
        f = font(size)
        box = d.textbbox((0, 0), label, font=f)
        if box[2] - box[0] <= 270:
            break
    d.text((160, 90), label, font=f, fill=ink, anchor="mm")
    return im


def install_builtin(library: AssetLibrary, id: str):
    if id not in BUILTINS:
        raise EngineError("unknown built-in asset pack")
    session = Session.new()
    name, _, labels = BUILTINS[id]
    entries = []
    for index, label in enumerate(labels):
        im = _sticker(id, index, label)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        source = Source(kind="builtin-pack", title=f"{name}: {label}", creator="badshop procedural artwork",
                        license="MIT", page=None)
        meta = session.artifacts.add(buf.getvalue(), label, source=source)
        entries.append(library.save(session, meta.id, label, [id, "prop", "transparent"],
                                   AssetDetails(anchors={"center": (160, 90), "bottom": (160, 179)},
                                                notes=f"Original geometric artwork drawn by badshop; pack: {name}.")))
    return entries


def _absolute(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise EngineError("choose an absolute pack file path")
    return p


def export_pack(library: AssetLibrary, ids: list[str], path: str, name: str = "My badshop pack"):
    if not 1 <= len(ids) <= MAX_ITEMS or len(set(ids)) != len(ids):
        raise EngineError(f"choose 1 to {MAX_ITEMS} distinct assets")
    entries = [library.get(id) for id in ids]
    blobs = {}
    for entry in entries:
        for meta in (entry.artifact, entry.original):
            if meta is not None:
                blob = library._blob(meta)
                if len(blob) > MAX_ENTRY:
                    raise EngineError("an image is too large for a pack (20 MB limit)")
                blobs[f"images/{meta.id}{meta.ext}"] = blob
    manifest = json.dumps({"schema": 1, "name": name, "entries": [e.model_dump(mode="json") for e in entries]}).encode()
    if len(manifest) > 2**20 or sum(map(len, blobs.values())) > MAX_PACK:
        raise EngineError("the pack exceeds its 80 MB image or 1 MB metadata limit")
    destination = _absolute(path)
    created = False
    try:
        with destination.open("xb") as target:
            created = True
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("pack.json", manifest)
                for filename, blob in blobs.items():
                    archive.writestr(filename, blob)
    except OSError as e:
        if created:
            destination.unlink(missing_ok=True)
        raise EngineError(f"could not export pack: {e}", hint="choose a new filename in an existing folder") from None
    return {"path": str(destination), "count": len(entries)}


def import_pack(library: AssetLibrary, path: str):
    source = _absolute(path)
    try:
        if source.stat().st_size > MAX_PACK + 2 * 2**20:
            raise EngineError("pack is too large (80 MB limit)")
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            names = [info.filename for info in members]
            if len(names) > MAX_ITEMS * 2 + 1 or len(set(names)) != len(names) or "pack.json" not in names:
                raise EngineError("pack has duplicate, missing, or excessive members")
            for info in members:
                if ("\\" in info.filename or info.filename.startswith("/") or ".." in info.filename.split("/")
                        or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                    raise EngineError("unsafe pack member")
                if info.file_size > (2**20 if info.filename == "pack.json" else MAX_ENTRY):
                    raise EngineError("pack member exceeds size limit")
            if sum(info.file_size for info in members) > MAX_PACK + 2**20:
                raise EngineError("unpacked assets exceed the pack limit")
            manifest = json.loads(archive.read("pack.json"))
            if manifest.get("schema") != 1 or not isinstance(manifest.get("entries"), list):
                raise EngineError("unsupported asset pack format")
            raw_entries = manifest["entries"]
            if not 1 <= len(raw_entries) <= MAX_ITEMS:
                raise EngineError("pack must contain 1 to 100 assets")
            entries = [LibraryEntry.model_validate(entry) for entry in raw_entries]
            expected = {"pack.json"}
            blobs = {}
            for entry in entries:
                if entry.artifact.original_id and (entry.original is None or entry.original.id != entry.artifact.original_id):
                    raise EngineError("pack original reference does not match the supplied original")
                library._tags(entry.tags)
                for meta in (entry.original, entry.artifact):
                    if meta is None:
                        continue
                    filename = f"images/{meta.id}{meta.ext}"
                    expected.add(filename)
                    if filename in blobs:
                        continue
                    data = archive.read(filename)
                    if hashlib.sha256(data).hexdigest() != meta.id:
                        raise EngineError("pack image hash does not match")
                    checked = ArtifactStore()
                    actual = checked.add(data, meta.label)
                    if (actual.width, actual.height, actual.format) != (meta.width, meta.height, meta.format):
                        raise EngineError("pack image metadata does not match its pixels")
                    blobs[filename] = data
            if set(names) != expected:
                raise EngineError("pack contains unexpected files")
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, TypeError, AttributeError, ValidationError, RuntimeError, NotImplementedError) as e:
        raise EngineError(f"could not import asset pack: {e}") from None
    # Commit only after every record and image has passed validation; existing entries never overwrite.
    library.root.mkdir(parents=True, exist_ok=True)
    installed = []
    try:
        for filename, data in blobs.items():
            dest = library.root / Path(filename).name
            if not dest.exists():
                tmp = dest.with_suffix(f".{uuid.uuid4().hex}.tmp")
                try:
                    tmp.write_bytes(data)
                    os.replace(tmp, dest)
                finally:
                    tmp.unlink(missing_ok=True)
        now = time.time()
        for entry in entries:
            new = entry.model_copy(update={"id": uuid.uuid4().hex, "created_at": now, "updated_at": now})
            installed.append(library._write(new))
    except (OSError, EngineError):
        for entry in installed:
            library._path(entry["id"]).unlink(missing_ok=True)
        raise EngineError("could not install the pack; no new library entries were kept") from None
    return {"entries": installed, "name": str(manifest.get("name") or "Imported pack")[:200], "count": len(installed)}
