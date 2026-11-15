"""Explicit online material selection, independent of the recorded tool timeline."""

import asyncio
import threading
from typing import Annotated

from pydantic import Field

from badshop.agent.loop import _to_the_end
from badshop.engine.discovery import AcquireParams, DiscoverParams
from badshop.engine.errors import EngineError
from badshop.server.rpc import OPERATION_ID
from badshop.session import branches
from badshop.session.execution import ToolCall
from badshop.session.models import Source, Step
from badshop.tools import runner


def import_receipt(base_revision: int, result_revision: int) -> dict:
    return {"operation_id": OPERATION_ID.get(), "base_revision": base_revision, "result_revision": result_revision}


def import_result(working, original, base_revision: int, result_revision: int) -> dict:
    return {"working": working.model_dump(mode="json"), "original": original.model_dump(mode="json"),
            **import_receipt(base_revision, result_revision)}


def register(app):
    active: tuple[threading.Event, asyncio.Event] | None = None

    async def stop():
        if active:
            cancel, finished = active
            cancel.set()
            await finished.wait()

    async def execute(tool, params, expected_revision=None):
        nonlocal active
        if active is not None:
            raise EngineError("another online material request is running", hint="wait for it to finish")
        cancel, finished = threading.Event(), asyncio.Event()
        active = cancel, finished

        def allow_online():
            app._check_idle()
            if app.settings.no_remote:
                raise EngineError("Local only blocks online material searches and downloads",
                                  hint="import a local picture or turn off Local only in Settings")

        def prepare():
            allow_online()
            app._check_revision(expected_revision, "used to import material")
            session = app.session
            raw = params.model_dump(mode="json", exclude_unset=True)
            if tool == "discover":
                raw = session._discovery_params(raw)
            resolved = session._resolved(runner.validate(tool, raw, "user"))
            draft = Step(id="material", index=0, tool=tool, params=resolved, actor="user", status="proposed")
            # No selected result is a trusted typed URL. Keep the worker's public-network policy
            # active for the candidate, any page fallback and all redirects.
            call = ToolCall(tool, resolved, session._inputs(draft), "",
                            output_mode="metadata" if tool == "discover" else "original")
            return session, session.data.active_branch_id, app._document_revision, call

        try:
            session, branch_id, revision, call = await app._blocking(prepare)
            # The existing bounded worker owns all download/decode work. Its per-call bytes
            # store is discarded on success, error, cancellation and stale ownership.
            pending = asyncio.create_task(asyncio.to_thread(session.executor.run, call, cancel=cancel))
            try:
                outcome = await asyncio.shield(pending)
            except asyncio.CancelledError:
                cancel.set()
                await _to_the_end(pending)
                raise
            if not outcome.ok:
                raise EngineError(outcome.error_message or "online material failed", hint=outcome.error_hint)

            def finish():
                allow_online()
                if cancel.is_set():
                    raise EngineError("online material request stopped")
                if app.session is not session or session.data.active_branch_id != branch_id:
                    raise EngineError("the session changed while looking up this material",
                                      hint="choose material again in the current session")
                app._check_revision(revision, "used to finish the material request")
                if tool == "discover":
                    return {key: outcome.data[key] for key in
                            ("query", "candidates", "source_health", "duplicates_removed", "warnings")}
                if len(outcome.outputs) != 1 or not outcome.data.get("sources"):
                    raise EngineError("the source did not produce one material picture")
                output = outcome.outputs[0]
                source = Source.model_validate(outcome.data["sources"][0])
                with branches.manual_edit(session, "import online material"):
                    working = session.import_image(output.data, source.title or output.name_hint, source)
                original = session.artifacts.meta.get(working.original_id or "", working)
                return import_result(working, original, revision, app._document_revision)

            return await app._blocking(finish, publishing_import=tool == "acquire")
        finally:
            active = None
            finished.set()

    async def discover(actor: str, params: DiscoverParams):
        return await execute("discover", params)

    async def acquire(actor: str, params: AcquireParams, expected_revision: Annotated[int, Field(strict=True, ge=0)]):
        return await execute("acquire", params, expected_revision)

    app.dispatcher.method("materials.discover", actors="user")(discover)
    app.dispatcher.method("materials.acquire", actors="user")(acquire)
    return stop
