"""User-only media and collection endpoints, registered by CoreApp after initialization."""
from typing import Annotated, Literal
import threading
import base64
import binascii
import tempfile
from pathlib import Path

from pydantic import Field

from badshop.session.media import MediaSources
from badshop.session.local_collection import LocalCollections
from badshop.session import branches
from badshop.engine.errors import EngineError

Count = Annotated[int, Field(ge=1, le=12)]
Time = Annotated[float, Field(ge=0, le=86400)]
Page = Annotated[int, Field(ge=1, le=100000)]
PathText = Annotated[str, Field(min_length=1, max_length=4096)]
Identifier = Annotated[str, Field(min_length=1, max_length=64)]
Tags = Annotated[list[Annotated[str, Field(max_length=80)]], Field(max_length=50)]


def register(app):
    media, collections = MediaSources(), LocalCollections()
    pending: set[threading.Event] = set()

    async def status(actor: str):
        return {"video": True, "pdf": True}

    async def cancel(actor: str):
        for signal in pending:
            signal.set()
        return {"cancelled": bool(pending)}

    async def capture(actor: str):
        return await extract("capture", media.root)

    async def discard(actor: str, preview_id: Identifier):
        await app._blocking(media.discard, preview_id)
        return {"discarded": True}

    async def extract(operation, root, **params):
        signal = threading.Event()
        pending.add(signal)
        try:
            return await app._blocking(app._decoder.media, operation, str(root), cancel=signal, **params)
        finally:
            pending.discard(signal)

    async def preview(actor: str, kind: Literal["video", "document"], path: PathText | None = None,
                      data: Annotated[str, Field(max_length=66_000_000)] | None = None,
                      name: Annotated[str, Field(max_length=256)] = "source",
                      start: Time = 0, end: Time | None = None, count: Count = 8, page: Page = 1):
        if (path is None) == (data is None):
            raise EngineError("choose either a local file or uploaded media bytes")
        options = dict(kind=kind, start=start, end=end, count=count, page=page)
        if path is not None:
            return await extract("preview", media.root, path=path, **options)
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            raise EngineError("uploaded media is not valid base64") from None
        if len(raw) > 47 * 2**20:
            raise EngineError("uploaded media exceeds 47 MiB; choose a local file instead")
        filename = name.replace("\\", "/").rsplit("/", 1)[-1]
        if filename in ("", ".", ".."):
            raise EngineError("choose a named media file")
        with tempfile.TemporaryDirectory(prefix="badshop-upload-") as folder:
            chosen = Path(folder) / filename
            await app._blocking(chosen.write_bytes, raw)
            return await extract("preview", media.root, path=str(chosen), **options)

    async def import_media(actor: str, preview_id: Identifier,
                           candidate_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)],
                           crop: tuple[int, int, int, int] | None = None, animate: bool = False,
                           delay: Annotated[int, Field(ge=20, le=10000)] = 100):
        def apply():
            app._check_idle()
            with branches.manual_edit(app.session, "import media"):
                return media.import_selected(app.session, preview_id, candidate_ids, crop, animate, delay)
        return await app._blocking(apply)

    async def index(actor: str, path: PathText, max_files: Annotated[int, Field(ge=1, le=2000)] = 500):
        return await extract("index", collections.root, path=path, max_files=max_files)

    async def listing(actor: str):
        return await app._blocking(collections.list)

    async def search(actor: str, id: Identifier, query: Annotated[str, Field(max_length=300)] = "",
                     limit: Annotated[int, Field(ge=1, le=100)] = 50):
        return await app._blocking(collections.search, id, query, limit)

    async def update(actor: str, collection_id: Identifier, id: Identifier, tags: Tags | None = None,
                     description: Annotated[str, Field(max_length=4096)] | None = None):
        return await app._blocking(collections.update, collection_id, id, tags, description)

    async def import_collection(actor: str, collection_id: Identifier, id: Identifier):
        def apply():
            app._check_idle()
            with branches.manual_edit(app.session, "import collection image"):
                return collections.restore(app.session, collection_id, id)
        return await app._blocking(apply)

    async def remove(actor: str, id: Identifier):
        return await app._blocking(collections.remove, id)

    for method, handler in (("media.status", status), ("media.cancel", cancel), ("media.capture", capture), ("media.discard", discard), ("media.preview", preview), ("media.import", import_media),
        ("collections.index", index), ("collections.list", listing), ("collections.search", search),
        ("collections.update", update), ("collections.import", import_collection), ("collections.remove", remove)):
        app.dispatcher.method(method, actors="user")(handler)
