"""Retro catalog, portable preferences, bounded recipes and ancestry credits."""

import asyncio
import base64
import io
import json
import threading
from typing import Annotated
from pydantic import Field
from badshop.engine import retro
from badshop.agent.loop import _to_the_end
from badshop.engine.errors import EngineError
from badshop.session.preferences import CreativePreferences
from badshop.session import recipes


def register(app):
    app._recipe_cancel = None

    @app.dispatcher.method("artifacts.frame", actors="user")
    async def frame(actor: str, id: str, frame: Annotated[int, Field(ge=0, le=1000)] = 0):
        def decode():
            aid = app.session.artifacts.resolve(id)
            meta = app.session.artifacts.meta[aid]
            if frame >= meta.frames:
                raise EngineError("frame is outside this animation")
            im = app.session.artifacts.image(aid)
            im.seek(frame)
            out = io.BytesIO()
            im.convert("RGBA").save(out, "PNG")
            return {
                "meta": meta.model_dump(mode="json"),
                "mime": "image/png",
                "data": base64.b64encode(out.getvalue()).decode(),
            }

        return await app._blocking(decode)

    @app.dispatcher.method("sources.key", actors="user")
    async def source_key(actor: str, source: str, api_key: str = ""):
        from badshop.engine.source_keys import set_key

        return await app._blocking(set_key, source, api_key)

    @app.dispatcher.method("cache.status", actors="user")
    async def cache_status(actor: str):
        from badshop.engine.assets import data_dir

        folder = data_dir() / "source-previews"
        files = list(folder.glob("*.json"))
        return {"bytes": sum(p.stat().st_size for p in files), "files": len(files), "budget_mb": 512}

    @app.dispatcher.method("cache.clear", actors="user")
    async def cache_clear(actor: str):
        from badshop.engine.assets import data_dir

        def clear():
            cache = data_dir() / 'source-previews'
            if cache.is_symlink():
                raise EngineError('the disposable cache is a link; refusing to clear another folder')
            folder = cache.resolve()
            count = 0
            for path in folder.glob("*.json"):
                if path.resolve().parent == folder and path.is_file():
                    path.unlink()
                    count += 1
            return {"removed": count}

        return await app._blocking(clear)

    @app.dispatcher.method("retro.list", actors="any")
    async def listing(actor: str):
        def build():
            rows = []
            for style in retro.STYLES.values():
                p = retro.RetroParams(
                    style=style["id"], title="BADSHOP" if style["width"] >= 150 else "MY PAGE"
                )
                im = retro.render(p, []).outputs[0]
                rows.append(
                    {**style, "preview": "data:image/png;base64," + base64.b64encode(im.encode()).decode()}
                )
            return rows

        return await app._blocking(build)

    @app.dispatcher.method("creative.set", actors="user")
    async def creative_set(actor: str, values: dict):
        def change():
            app._check_idle()
            prefs = CreativePreferences.model_validate({**app.session.data.creative.model_dump(), **values})
            for aid in prefs.source_roles.values():
                app.session.artifacts.resolve(aid)
            app.session.data.creative = prefs
            app.session.changes.append('The user updated creative preferences: ' + prefs.model_dump_json(exclude={'favorite_briefs', 'saved_searches', 'favorite_styles'}))
            app.session._changed()
            return prefs.model_dump(mode="json")

        return await app._blocking(change)

    @app.dispatcher.method("recipes.capture", actors="user")
    async def capture(actor: str, step_id: str):
        return await app._blocking(lambda: recipes.capture(app.session, step_id).model_dump(mode="json"))

    @app.dispatcher.method("recipes.save", actors="user")
    async def save(actor: str, recipe: dict):
        item = recipes.Recipe.model_validate(recipe).model_dump(mode="json")

        def change():
            app._check_idle()
            rows = [r for r in app.session.data.recipes if r.get("name") != item["name"]]
            if len(rows) >= 50:
                raise EngineError("a project holds at most 50 recipes")
            app.session.data.recipes = [*rows, item]
            app.session._changed()
            return item

        return await app._blocking(change)

    @app.dispatcher.method("recipes.remove", actors="user")
    async def remove(actor: str, name: str):
        def change():
            app._check_idle()
            app.session.data.recipes = [r for r in app.session.data.recipes if r.get("name") != name]
            app.session._changed()
            return {"removed": True}

        return await app._blocking(change)

    @app.dispatcher.method("recipes.run", actors="user")
    async def batch(
        actor: str, recipe: dict, inputs: Annotated[list[str], Field(min_length=1, max_length=12)]
    ):
        parsed = recipes.Recipe.model_validate(recipe)
        if len(parsed.steps) * len(inputs) > 60:
            raise EngineError("a batch is limited to 60 tool steps")
        app._check_idle()
        owned = app.session
        ids = [owned.artifacts.resolve(ref) for ref in inputs]
        signal = threading.Event()
        app._recipe_cancel = signal
        work = asyncio.create_task(app._blocking(recipes.run, owned, parsed, ids, signal))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            signal.set()
            await _to_the_end(work)
            raise
        finally:
            app._recipe_cancel = None

    @app.dispatcher.method("recipes.stop", actors="user")
    async def stop(actor: str):
        if app._recipe_cancel:
            app._recipe_cancel.set()
        return {"stopped": app._recipe_cancel is not None}

    @app.dispatcher.method("credits.get", actors="any")
    async def credits(actor: str, artifact_id: str):
        return await app._blocking(recipes.credits, app.session, artifact_id)

    @app.dispatcher.method("credits.export", actors="user")
    async def export(actor: str, artifact_id: str):
        def write():
            data = recipes.credits(app.session, artifact_id)
            # Existing image export selects a unique name; sidecar is exclusive too.
            path = app.session.export(artifact_id)
            try:
                with path.with_suffix(path.suffix + ".credits.json").open("x", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except OSError as e:
                raise EngineError(f"image saved to {path}, but credits could not be written: {e}") from None
            return {"path": str(path), "credits": str(path) + ".credits.json"}

        return await app._blocking(write)
