"""The session's images: immutable artifacts stored by the SHA-256 of their bytes (spec §5.3)."""

import hashlib
import io
import re
from collections.abc import Iterable
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError

from badshop.engine.common import fit, has_alpha, load_image, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.sources import slugify
from badshop.session.models import ArtifactMeta, Source

# The decoders an import may use: never EPS (it runs Ghostscript) or Pillow's rarer plugins (SEC-S1).
IMPORT_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF")
MAX_IMPORT_PIXELS = 100_000_000  # the most pixels any artifact may have; refused before decoding
WORKING_MAX = 1000  # an import's working copy: longest side in px, as `prep` makes
MIME: dict[str, str] = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp",
                        "BMP": "image/bmp", "TIFF": "image/tiff"}
FORMAT_ALIASES = {"MPO": "JPEG"}  # a phone's multi-picture JPEG opens as MPO; it is a JPEG file
MIN_PREFIX = 6
REF_HINT = "use an artifact id from a tool result, like a3f9c1d2"
FORMATS_HINT = "use a PNG, JPEG, GIF, WebP, BMP or TIFF image"


def short(id: str) -> str:
    return id[:8]


def describe(meta: ArtifactMeta) -> str:
    """How tool results and the step summary name an artifact: "a3f9c1d2 (lincoln_work, 761x1000)"."""
    return f"{short(meta.id)} ({meta.label}, {meta.width}x{meta.height})"


def _label(name: str) -> str:
    """A file name (or any text) as a label: its stem slugified, "pasted" when nothing usable is left, and
    without a trailing "_work", so re-importing badshop_work/lincoln_work.png is not lincoln_work_work."""
    stem = PurePath(name).stem if name else ""
    if not re.search(r"[a-z0-9]", stem.lower()):
        return "pasted"
    return re.sub(r"_work$", "", slugify(stem))


def _refused(name: str, e: Exception) -> EngineError:
    if isinstance(e, Image.DecompressionBombError):  # ours (over MAX_IMPORT_PIXELS) or Pillow's own limit
        return EngineError(f"{name} is too big ({e})", hint="use a smaller copy of the image "
                           f"(the limit is {MAX_IMPORT_PIXELS // 1_000_000} megapixels)")
    detail = "" if isinstance(e, UnidentifiedImageError) else f" ({e})"  # "cannot identify" names a BytesIO
    return EngineError(f"{name} isn't an image badshop can open{detail}", hint=FORMATS_HINT)


def _decode(data: bytes, name: str) -> Image.Image:
    """Bytes as an upright, fully loaded image, through the import decoders only. Hostile bytes can make
    a decoder raise almost anything (OSError, SyntaxError, ValueError, struct.error...): all become
    EngineError."""
    try:
        return load_image(data, formats=IMPORT_FORMATS, max_pixels=MAX_IMPORT_PIXELS)
    except Exception as e:
        raise _refused(name, e) from None


def _frames(im: Image.Image, name: str) -> int:
    """How many frames an opened image has. Counting reads on past the frame _decode loaded (a GIF's later
    frames, a TIFF's page chain), where damaged bytes raise just as freely: refused the same way."""
    try:
        return getattr(im, "n_frames", 1)
    except Exception as e:
        raise _refused(name, e) from None


class ArtifactStore:
    """Artifact bytes and metadata. An id is always the sha256 of the bytes, computed here, never trusted."""

    def __init__(self):
        self.meta: dict[str, ArtifactMeta] = {}
        self._data: dict[str, bytes] = {}

    def __contains__(self, id: object) -> bool:
        return id in self.meta

    def ids(self) -> list[str]:
        return list(self.meta)

    def add(self, data: bytes, label: str, *, produced_by: str | None = None, source: Source | None = None,
            original_id: str | None = None) -> ArtifactMeta:
        """Store bytes as an artifact. Bytes already stored return the existing meta unchanged, so an
        artifact keeps the label, produced_by and source it was first stored with."""
        id = hashlib.sha256(data).hexdigest()
        if id in self.meta:
            return self.meta[id]
        with _decode(data, label) as im:  # only images that open are stored, so image() never fails later
            fmt = FORMAT_ALIASES.get(im.format, im.format)
            meta = ArtifactMeta(id=id, label=label, width=im.width, height=im.height, format=fmt,
                                mime=MIME[fmt], frames=_frames(im, label), produced_by=produced_by,
                                source=source, original_id=original_id)
        self._data[id] = data
        self.meta[id] = meta
        return meta

    def data(self, id: str) -> bytes:
        try:
            return self._data[id]
        except KeyError:
            raise EngineError(f"no such artifact: {id}", hint=REF_HINT) from None

    def image(self, id: str) -> Image.Image:
        """A fresh decoded copy (upright; an animation is at its first frame)."""
        return _decode(self.data(id), self.meta[id].label)

    def resolve(self, ref: str) -> str:
        """A full id, or a unique prefix of at least 6 hex characters (any case), as the full id.
        Anything else, a path or URL included, is "no such artifact": this never touches the disk."""
        r = ref.strip().lower()
        if r in self.meta:
            return r
        if len(r) >= MIN_PREFIX and re.fullmatch(r"[0-9a-f]+", r):
            hits = [i for i in tuple(self.meta) if i.startswith(r)]  # tuple(): a snapshot across threads
            if len(hits) == 1:
                return hits[0]
            if hits:
                raise EngineError(f"artifact id {ref} is ambiguous ({len(hits)} artifacts start with it)",
                                  hint="give more characters of the id")
        raise EngineError(f"no such artifact: {ref}", hint=REF_HINT)

    def drop(self, ids: Iterable[str]) -> None:
        """Forget artifacts (ids not in the store are ignored)."""
        for id in list(ids):
            self.meta.pop(id, None)
            self._data.pop(id, None)

    def import_image(self, data: bytes, label: str, source: Source | None = None, *,
                     produced_by: str | None = None) -> tuple[ArtifactMeta, ArtifactMeta]:
        """A new image entering the session (a file, a drop, a paste, a fetched picture): returns
        (working copy, original).

        The working copy is what every tool sees: the first frame, upright, at most WORKING_MAX px, as PNG,
        keeping transparency (not `prep`, which flattens it). The original is the given bytes, unchanged,
        kept for provenance. Labels: "<name>_work" and "<name>" from the slugified file name stem.
        `produced_by` is the step that brought the picture in (a source tool's step), on every artifact
        this stores; None for the user's own import."""
        name = _label(label)
        with _decode(data, label or "the pasted data") as im:
            work, _ = fit(im.convert("RGBA") if has_alpha(im) else to_rgb(im), WORKING_MAX)
        buf = io.BytesIO()
        work.save(buf, "PNG")
        work_bytes = buf.getvalue()
        if work_bytes == data:  # a small upright PNG from badshop is its own working copy: stored once
            meta = self.add(data, f"{name}_work", produced_by=produced_by, source=source)
            return meta, meta
        original = self.add(data, name, produced_by=produced_by, source=source)
        working = self.add(work_bytes, f"{name}_work", produced_by=produced_by, source=source,
                           original_id=original.id)
        return working, original
