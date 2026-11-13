"""User-only asset pack management, registered separately to keep CoreApp small."""
import base64
from typing import Annotated

from pydantic import Field

from badshop.engine.layouts import definitions
from badshop.session import packs

Ids = Annotated[list[str], Field(min_length=1, max_length=100)]
Name = Annotated[str, Field(min_length=1, max_length=200)]


def register(app):
    @app.dispatcher.method("tools.preview", actors="user")
    async def preview(actor: str, tool: str, params: dict, expected_revision: int):
        def render():
            app._check_idle()
            app._check_revision(expected_revision, "previewed")
            return ["data:image/png;base64," + base64.b64encode(record.data).decode()
                    for record in app.session.preview_tool(tool, params)]
        return await app._blocking(render)

    @app.dispatcher.method("layouts.list", actors="user")
    async def layouts_list(actor: str):
        return definitions()

    @app.dispatcher.method("packs.list", actors="user")
    async def packs_list(actor: str):
        return packs.listing()

    @app.dispatcher.method("packs.install", actors="user")
    async def packs_install(actor: str, id: str):
        return await app._blocking(packs.install_builtin, app.library, id)

    @app.dispatcher.method("packs.export", actors="user")
    async def packs_export(actor: str, ids: Ids, path: str, name: Name = "My badshop pack"):
        return await app._blocking(packs.export_pack, app.library, ids, path, name)

    @app.dispatcher.method("packs.import", actors="user")
    async def packs_import(actor: str, path: str):
        return await app._blocking(packs.import_pack, app.library, path)
