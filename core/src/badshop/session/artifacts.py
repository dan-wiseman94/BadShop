"""Logical image uses with immutable SHA-256-addressed bytes (spec §5.3)."""

import hashlib
import io
import re
import os
import shutil
import uuid
import json
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path, PurePath

from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

from badshop.engine.common import fit, has_alpha, load_image, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.sources import slugify
from badshop.session.models import ArtifactMeta, Source
from badshop.session.blobs import BlobStore

# The decoders an import may use: never EPS (it runs Ghostscript) or Pillow's rarer plugins (SEC-S1).
register_heif_opener()
IMPORT_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF", "AVIF", "HEIF")
MAX_IMPORT_PIXELS = 100_000_000  # the most pixels any artifact may have; refused before decoding
MAX_STORED_BYTES = 2 * 2**30  # same payload ceiling as project archives; originals count too
REPRESENTATION_BYTES = 32 * 2**20
WORKING_MAX = 1000  # an import's working copy: longest side in px, as `prep` makes
MIME: dict[str, str] = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp",
                        "BMP": "image/bmp", "TIFF": "image/tiff", "AVIF": "image/avif", "HEIF": "image/heif"}
FORMAT_ALIASES = {"MPO": "JPEG"}  # a phone's multi-picture JPEG opens as MPO; it is a JPEG file
MIN_PREFIX = 6
REF_HINT = "use an artifact id from a tool result, like a3f9c1d2"
FORMATS_HINT = "use a PNG, JPEG, GIF, WebP, BMP, TIFF, AVIF or HEIC/HEIF image"


def _use_id(blob_id, label, source, original_id, invocation_id, output_key, input_ids=()):
    if invocation_id is None or output_key is None:
        return uuid.uuid4().hex + uuid.uuid4().hex
    # A stable version of one named output. Equal bytes in another invocation
    # remain a distinct use; replaying unchanged bytes preserves this use.
    body = [blob_id, label, source.model_dump() if source else None, original_id, invocation_id, output_key, input_ids]
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode('ascii')).hexdigest()


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


def _working_copy(im: Image.Image, name: str) -> bytes:
    """An opened image's working copy as PNG bytes: at most WORKING_MAX px, transparency kept. Converting
    can meet damage the decode let through (a tRNS chunk longer than the palette): refused the same way."""
    try:
        work, _ = fit(im.convert("RGBA") if has_alpha(im) else to_rgb(im), WORKING_MAX)
        buf = io.BytesIO()
        work.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        raise _refused(name, e) from None


class ArtifactStore:
    """Distinct provenance records share immutable blobs; derived views are disposable."""

    def __init__(self, decoder: Callable[[bytes, str, int], Image.Image] | None = None):
        self.meta: dict[str, ArtifactMeta] = {}
        self._data: dict[str, Path] = {}
        self.decoder = decoder
        self._representations: OrderedDict[tuple, bytes] = OrderedDict()
        self._representation_size = 0
        self._representation_lock = threading.Lock()

    def representation(self, aid: str, options: tuple, produce: Callable[[], bytes]) -> bytes:
        """Cache encoded views by content and complete rendering options, bounded by bytes.

        The store owns this cache; closing a document releases it. Callers provide a
        rendering version, frame, dimensions and encoding, never a mutable use ID.
        Decoding stays on the existing decoder path and outside the cache lock.
        """
        key = (self.meta[aid].blob_id, *options)
        with self._representation_lock:
            if key in self._representations:
                self._representations.move_to_end(key)
                return self._representations[key]
        data = produce()
        if len(data) <= REPRESENTATION_BYTES:
            with self._representation_lock:
                previous = self._representations.pop(key, b'')
                self._representation_size -= len(previous)
                while self._representations and self._representation_size + len(data) > REPRESENTATION_BYTES:
                    _, evicted = self._representations.popitem(last=False)
                    self._representation_size -= len(evicted)
                self._representations[key] = data
                self._representation_size += len(data)
        return data

    @cached_property
    def _blobs(self):
        return BlobStore()

    def close(self):
        with self._representation_lock:
            self._representations.clear()
            self._representation_size = 0
        if '_blobs' in self.__dict__:
            self._blobs.close()

    def _open(self, data: bytes, name: str, frame: int = 0) -> Image.Image:
        if self.decoder is not None:
            return self.decoder(data, name, frame)
        image = _decode(data, name)
        try:
            if frame:
                image.seek(frame)
                image.load()
            return image
        except Exception as error:
            image.close()
            raise _refused(name, error) from None

    def __contains__(self, id: object) -> bool:
        return id in self.meta

    def ids(self) -> list[str]:
        return list(self.meta)

    def _capacity(self, *blobs: bytes) -> None:
        incoming = {hashlib.sha256(blob).hexdigest(): len(blob) for blob in blobs}
        paths = set(self._data.values())
        stored = {path.name for path in paths}
        total = sum(path.stat().st_size for path in paths) + sum(size for aid, size in incoming.items() if aid not in stored)
        if total > MAX_STORED_BYTES:
            raise EngineError("this project has reached its 2 GB image storage limit",
                              hint="save this project and start another, or remove unused images")

    @contextmanager
    def atomic(self):
        """A serialized session mutation installs its whole batch or none of it."""
        before = set(self.meta)
        try:
            yield
        except BaseException:
            self.drop(set(self.meta) - before)
            raise

    def add(self, data: bytes, label: str, *, produced_by: str | None = None, source: Source | None = None,
            original_id: str | None = None, new_use: bool = False, identity: str | None = None,
            invocation_id: str | None = None, output_key: str | None = None,
            input_ids: tuple[str, ...] = (), legacy_identity: bool = False) -> ArtifactMeta:
        """Store one immutable use. Existing identities retain their original metadata.

        Product imports/outputs request distinct uses. Content identities remain
        available for internal decoder fixtures and supported legacy archives.
        """
        blob_id = hashlib.sha256(data).hexdigest()
        id = identity or (_use_id(blob_id, label, source, original_id, invocation_id, output_key, input_ids) if new_use else blob_id)
        if id in self.meta:
            if self.meta[id].blob_id != blob_id:
                raise EngineError('artifact use cannot change its immutable bytes')
            return self.meta[id]
        self._capacity(data)
        with self._open(data, label) as im:  # only images that open are stored, so image() never fails later
            fmt = FORMAT_ALIASES.get(im.format, im.format)
            meta = ArtifactMeta(id=id, blob_id=blob_id, invocation_id=invocation_id, output_key=output_key,
                                inputs=input_ids, legacy_identity=legacy_identity,
                                label=label, width=im.width, height=im.height, format=fmt,
                                mime=MIME[fmt], frames=_frames(im, label), produced_by=produced_by,
                                source=source, original_id=original_id)
        self._data[id] = self._blobs.put(data)
        self.meta[id] = meta
        return meta

    def data(self, id: str) -> bytes:
        try:
            path = self._data[id]
        except KeyError:
            raise EngineError(f"no such artifact: {id}", hint=REF_HINT) from None
        return self._blobs.read(path, self.meta[id].blob_id)

    def clone_use(self, id: str, *, produced_by: str, invocation_id: str, output_key: str) -> ArtifactMeta:
        source = self.meta[id]
        identity = _use_id(source.blob_id, source.label, source.source, source.original_id, invocation_id, output_key, source.inputs)
        meta = self.meta[id].model_copy(update={'id': identity, 'produced_by': produced_by,
            'invocation_id': invocation_id, 'output_key': output_key, 'legacy_identity': False})
        self.meta[identity], self._data[identity] = meta, self._data[id]
        return meta

    def size(self, id: str) -> int:
        return self._data[id].stat().st_size

    def fork(self):
        """Borrow immutable inputs, but own all temporary preview outputs separately."""
        store = ArtifactStore(decoder=self.decoder)
        store.meta = dict(self.meta)
        for aid, path in self._data.items():
            target = store._blobs.path(self.meta[aid].blob_id)
            if target.exists():
                store._data[aid] = target
                continue
            try:
                os.link(path, target)
            except OSError:
                shutil.copyfile(path, target)
            store._data[aid] = target
        return store

    def image(self, id: str, frame: int = 0) -> Image.Image:
        """A fresh decoded copy (upright; an animation is at its first frame)."""
        return self._open(self.data(id), self.meta[id].label, frame)

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
            path = self._data.get(id)
            self.meta.pop(id, None)
            self._data.pop(id, None)
            if path is not None and path not in self._data.values():
                path.unlink(missing_ok=True)

    def import_image(self, data: bytes, label: str, source: Source | None = None, *,
                     produced_by: str | None = None, invocation_id: str | None = None,
                     output_key: str | None = None) -> tuple[ArtifactMeta, ArtifactMeta]:
        """A new image entering the session (a file, a drop, a paste, a fetched picture): returns
        (working copy, original).

        The working copy is what every tool sees: the first frame, upright, at most WORKING_MAX px, as PNG,
        keeping transparency (not `prep`, which flattens it). The original is the given bytes, unchanged,
        kept for provenance. Labels: "<name>_work" and "<name>" from the slugified file name stem.
        `produced_by` is the step that brought the picture in (a source tool's step), on every artifact
        this stores; None for the user's own import."""
        name, shown = _label(label), label or "the pasted data"
        with self._open(data, shown) as im:
            work_bytes = _working_copy(im, shown)
        self._capacity(data, work_bytes)  # refuse before storing either half of an import
        if work_bytes == data:  # a small upright PNG from badshop is its own working copy: stored once
            meta = self.add(data, f"{name}_work", produced_by=produced_by, source=source,
                            new_use=True, invocation_id=invocation_id, output_key=output_key)
            return meta, meta
        with self.atomic():
            original = self.add(data, name, produced_by=produced_by, source=source, new_use=True,
                                invocation_id=invocation_id, output_key=f'{output_key}:original' if output_key else None)
            working = self.add(work_bytes, f"{name}_work", produced_by=produced_by, source=source,
                               original_id=original.id, new_use=True, invocation_id=invocation_id, output_key=output_key)
        return working, original
