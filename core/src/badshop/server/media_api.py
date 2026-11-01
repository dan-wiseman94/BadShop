"""User-only media and collection endpoints, registered by CoreApp after initialization."""
from typing import Annotated, Literal

from pydantic import Field

from badshop.session.media import MediaSources
from badshop.session.local_collection import LocalCollections

Count = Annotated[int, Field(ge=1, le=12)]
Time = Annotated[float, Field(ge=0, le=86400)]
Page = Annotated[int, Field(ge=1, le=100000)]
PathText = Annotated[str, Field(min_length=1, max_length=4096)]
Identifier = Annotated[str, Field(min_length=1, max_length=64)]
Tags = Annotated[list[Annotated[str, Field(max_length=80)]], Field(max_length=50)]


def register(app):
    media, collections = MediaSources(), LocalCollections()

    async def preview(actor: str, path: PathText, kind: Literal["video", "document"],
                      start: Time = 0, end: Time | None = None, count: Count = 8, page: Page = 1):
        return await app._blocking(media.preview, path, kind, start, end, count, page)

    async def import_media(actor: str, preview_id: Identifier,
                           candidate_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)],
                           crop: tuple[int, int, int, int] | None = None, animate: bool = False,
                           delay: Annotated[int, Field(ge=20, le=10000)] = 100):
        def apply():
            app._check_idle()
            return media.import_selected(app.session, preview_id, candidate_ids, crop, animate, delay)
        return await app._blocking(apply)

    async def index(actor: str, path: PathText, max_files: Annotated[int, Field(ge=1, le=2000)] = 500):
        return await app._blocking(collections.index, path, max_files)

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
            return collections.restore(app.session, collection_id, id)
        return await app._blocking(apply)

    async def remove(actor: str, id: Identifier):
        return await app._blocking(collections.remove, id)

    for method, handler in (("media.preview", preview), ("media.import", import_media),
        ("collections.index", index), ("collections.list", listing), ("collections.search", search),
        ("collections.update", update), ("collections.import", import_collection), ("collections.remove", remove)):
        app.dispatcher.method(method, actors="user")(handler)
