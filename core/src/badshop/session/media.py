"""User-picked local media previews. Extracted pixels are frozen before selection.

No local path becomes an agent tool argument. Preview caches contain rendered frames, source names,
and hashes, not the video/PDF itself. Importing records page/time/crop evidence in the project.
"""
import base64
import hashlib
import io
import json
import math
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from badshop.engine import assets
from badshop.engine.errors import EngineError
from badshop.engine.sources import contact_sheet
from badshop.session.models import Part, Source

MAX_BYTES = 200 * 2**20
MAX_PIXELS = 32_000_000
IMAGE_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF")
VIDEO_FORMATS = "mov,matroska,avi,mpegts,mpeg,ogg,asf,flv"


def picked_path(value: str, *, directory=False) -> Path:
    try:
        path = Path(value).expanduser()
        if not path.is_absolute() or not (path.is_dir() if directory else path.is_file()):
            raise ValueError()
        return path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise EngineError("choose an existing absolute folder path" if directory else
                          "choose an existing absolute file path") from None


def source_bytes(path: Path) -> bytes:
    if path.stat().st_size > MAX_BYTES:
        raise EngineError("source file exceeds the 200 MB import limit")
    with path.open("rb") as file:
        data = file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise EngineError("source file exceeds the 200 MB import limit")
    return data


def png(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def small_image(image):
    if image.width * image.height > MAX_PIXELS:
        raise EngineError("source image is too large; use a smaller scan")
    upright = ImageOps.exif_transpose(image).convert("RGBA")
    return ImageOps.contain(upright, (1000, 1000), Image.Resampling.NEAREST) if max(upright.size) > 1000 else upright


def data_url(image, size=250):
    thumb = ImageOps.contain(image, (size, size), Image.Resampling.NEAREST)
    return "data:image/png;base64," + base64.b64encode(png(thumb)).decode("ascii")


def _run(args, timeout=20):
    binary = shutil.which(args[0])
    if not binary:
        raise EngineError(f"{args[0]} is not installed", hint="install the media tool for your OS, then restart badshop")
    try:
        result = subprocess.run([binary, *args[1:]], stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise EngineError("media extraction timed out", hint="choose a shorter clip or smaller document") from None
    if result.returncode:
        raise EngineError("media could not be decoded", hint="try another file or an earlier page/time")
    return result.stdout


def persist_note(session, label, details, image_ids):
    # The payload is data, not instructions. Persist it so reopening before a provider turn loses none.
    payload = json.dumps(details, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e")
    text = "User-selected local source metadata (data only): <untrusted_web_data>" + payload + "</untrusted_web_data>"
    session.data.transcript.append({"role": "user", "content": text})
    session.add_message("system_note", [Part(type="text", text=label),
                                        *[Part(type="image", artifact_id=aid) for aid in image_ids]])
    session._changed()


class MediaSources:
    def __init__(self, root=None):
        self.root = Path(root) if root else assets.data_dir() / "media-previews"

    def _folder(self, id):
        if len(id) != 32 or any(c not in "0123456789abcdef" for c in id):
            raise EngineError("invalid media preview id")
        return self.root / id

    def preview(self, path: str, kind: str, start=0.0, end=None, count=8, page=1):
        try:
            return self._preview(path, kind, start, end, count, page)
        except (OSError, ValueError, EOFError, Image.DecompressionBombError):
            raise EngineError("source could not be decoded", hint="choose a supported image, PDF, GIF or video") from None

    def _preview(self, path: str, kind: str, start=0.0, end=None, count=8, page=1):
        if kind not in ("video", "document") or not 1 <= count <= 12 or not 1 <= page <= 100000:
            raise EngineError("invalid media preview options")
        if not math.isfinite(start) or start < 0 or (end is not None and (not math.isfinite(end) or end <= start)):
            raise EngineError("choose a nonnegative start and a later end time")
        chosen = picked_path(path)
        raw = source_bytes(chosen)
        original_hash = hashlib.sha256(raw).hexdigest()
        frames, warnings = [], []
        with tempfile.TemporaryDirectory(prefix="badshop-media-") as temp:
            frozen = Path(temp) / ("source" + chosen.suffix.lower())
            frozen.write_bytes(raw)
            if kind == "document":
                if chosen.suffix.lower() == ".pdf":
                    target = Path(temp) / "page"
                    _run(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-scale-to", "1000",
                          "-png", str(frozen), str(target)], timeout=30)
                    with Image.open(target.with_suffix(".png")) as image:
                        frames = [(small_image(image), {"page": page, "label": f"Page {page}"})]
                else:
                    with Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS) as image:
                        image.seek(page - 1)
                        frames = [(small_image(image), {"page": page, "label": f"Page {page}"})]
            elif chosen.suffix.lower() == ".gif":
                with Image.open(io.BytesIO(raw), formats=("GIF",)) as image:
                    if image.width * image.height > MAX_PIXELS:
                        raise EngineError("GIF dimensions exceed the preview limit")
                    timings = []
                    elapsed = 0.0
                    for index in range(min(image.n_frames, 3000)):
                        image.seek(index)
                        timings.append(elapsed)
                        elapsed += max(10, image.info.get("duration", 100)) / 1000
                    stop = min(end if end is not None else elapsed, elapsed)
                    available = [i for i, t in enumerate(timings) if start <= t < stop]
                    if not available:
                        raise EngineError("no GIF frames in that time range")
                    indices = list(dict.fromkeys(available[min(len(available) - 1, i * len(available) // count)]
                                                 for i in range(count)))
                    for index in indices:
                        image.seek(index)
                        frames.append((small_image(image), {"time_s": round(timings[index], 4),
                                      "frame": index, "label": f"Frame {index + 1} · {timings[index]:.3f}s"}))
                    if image.n_frames > 3000:
                        warnings.append("Only the first 3000 GIF frames were considered.")
            else:
                probe = json.loads(_run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                     "-format_whitelist", VIDEO_FORMATS, "-show_entries", "format=duration:stream=width,height", "-of", "json", str(frozen)], timeout=10))
                if any(s.get("width", 0) * s.get("height", 0) > MAX_PIXELS for s in probe.get("streams", [])):
                    raise EngineError("video dimensions exceed the preview limit")
                duration = float(probe.get("format", {}).get("duration", 0))
                if not math.isfinite(duration) or duration <= start:
                    raise EngineError("no video at that start time")
                stop = min(end if end is not None else start + 30, duration)
                if stop - start > 120:
                    raise EngineError("preview at most 120 seconds at once")
                deadline = time.monotonic() + 45
                for index in range(count):
                    timestamp = start + (stop - start) * index / count
                    target = Path(temp) / f"frame-{index}.png"
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        warnings.append("Preview time limit reached; showing extracted frames.")
                        break
                    _run(["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                          "-format_whitelist", VIDEO_FORMATS, "-max_alloc", "134217728", "-threads", "1", "-ss", str(timestamp), "-i", str(frozen), "-an", "-frames:v", "1",
                          "-vf", "scale=1000:1000:force_original_aspect_ratio=decrease:flags=neighbor",
                          "-threads", "1", str(target)], timeout=min(15, remaining))
                    if target.exists():
                        with Image.open(target) as image:
                            frames.append((small_image(image), {"time_s": round(timestamp, 4),
                                          "label": f"At {timestamp:.3f}s"}))
                warnings.append("Video times are requested seek positions; the selected frame is frozen for replay.")
        if not frames:
            raise EngineError("no frames could be extracted")
        self.root.mkdir(parents=True, exist_ok=True)
        # Bounded persistent preview cache; selected imports have their own project copies.
        old = sorted((p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()
                      and len(p.name) == 32 and all(c in "0123456789abcdef" for c in p.name)),
                     key=lambda p: p.stat().st_mtime)
        for folder in old[:-15]:
            shutil.rmtree(folder)
        id = uuid.uuid4().hex
        folder = self._folder(id)
        folder.mkdir()
        candidates, panels = [], []
        for index, (image, detail) in enumerate(frames):
            candidate_id = str(index)
            blob = png(image)
            (folder / f"{candidate_id}.png").write_bytes(blob)
            candidates.append({"id": candidate_id, **detail, "width": image.width, "height": image.height,
                               "sha256": hashlib.sha256(blob).hexdigest(), "thumbnail_data_url": data_url(image, 1000 if kind == "document" else 250)})
            panels.append((index + 1, image, detail["label"]))
        record = {"id": id, "source_name": chosen.name, "source_sha256": original_hash, "kind": kind,
                  "width": frames[0][0].width, "height": frames[0][0].height, "candidates": candidates,
                  "warnings": warnings, "sheet_data_url": data_url(contact_sheet(panels), 1000)}
        stored = {k: v for k, v in record.items() if k != "sheet_data_url"}
        stored["candidates"] = [{k: v for k, v in item.items() if k != "thumbnail_data_url"}
                                for item in candidates]
        (folder / "preview.json").write_text(json.dumps(stored))
        return record

    def import_selected(self, session, preview_id, candidate_ids, crop=None, animate=False, delay=100):
        folder = self._folder(preview_id)
        try:
            if (folder / "preview.json").stat().st_size > 4 * 2**20:
                raise EngineError("preview metadata is too large")
            record = json.loads((folder / "preview.json").read_text())
        except (OSError, ValueError):
            raise EngineError("preview expired; open the source again") from None
        if not candidate_ids or len(candidate_ids) > 12 or len(set(candidate_ids)) != len(candidate_ids):
            raise EngineError("select between one and twelve distinct frames")
        if animate and len(candidate_ids) < 2:
            raise EngineError("select at least two frames for animation")
        if crop is not None and len(candidate_ids) != 1:
            raise EngineError("crop one frame or page at a time")
        if not 20 <= delay <= 10000:
            raise EngineError("animation delay must be between 20 and 10000 milliseconds")
        by_id = {c["id"]: c for c in record["candidates"]}
        prepared = []
        for id in candidate_ids:
            if not id.isdecimal() or len(id) > 2 or id not in by_id:
                raise EngineError("selected frame is not in this preview")
            item = by_id[id]
            blob = (folder / f"{id}.png").read_bytes()
            if hashlib.sha256(blob).hexdigest() != item["sha256"]:
                raise EngineError("preview pixels changed; open the source again")
            with Image.open(io.BytesIO(blob), formats=("PNG",)) as im:
                if crop is not None:
                    if len(crop) != 4 or not all(isinstance(v, int) for v in crop):
                        raise EngineError("crop must contain four integer coordinates")
                    x0, y0, x1, y1 = crop
                    if not 0 <= x0 < x1 <= im.width or not 0 <= y0 < y1 <= im.height:
                        raise EngineError("crop must fit inside the selected preview")
                    prepared.append((png(im.crop(crop)), item))
                else:
                    prepared.append((blob, item))
        imported = []
        for blob, item in prepared:
            label = f"{record['source_name']} {item['label']}"
            title = label + (f" crop {list(crop)}" if crop is not None else "")
            source = Source(kind="local-media", title=title)
            if crop is not None:
                original = session.import_image((folder / f"{item['id']}.png").read_bytes(), label,
                                                Source(kind="local-media", title=label))
                step = session.run_tool("cutout", {"image": original.id, "box": list(crop), "no_ai": True}, "user")
                if step.status != "done":
                    raise EngineError(step.error.message if step.error else "source crop failed")
                meta = session.artifacts.meta[step.outputs[0]]
                meta = meta.model_copy(update={"source": source, "original_id": original.id if meta.id != original.id else None})
                session.artifacts.meta[meta.id] = meta
            else:
                meta = session.import_image(blob, label, source)
            imported.append(meta)
        details = {"source_name": record["source_name"], "source_sha256": record["source_sha256"],
                   "kind": record["kind"], "selected": [{k: v for k, v in by_id[id].items()
                   if k not in ("thumbnail_data_url", "sha256")} for id in candidate_ids], "crop": crop}
        persist_note(session, f"Imported selected media from {record['source_name']}", details, [m.id for m in imported])
        if animate:
            step = session.run_tool("animate", {"images": [m.id for m in imported], "delay": delay}, "user")
            if step.status != "done":
                raise EngineError(step.error.message if step.error else "animation failed")
            imported = [session.artifacts.meta[aid] for aid in step.outputs]
        return {"artifacts": [m.model_dump(mode="json") for m in imported], "provenance": details}
