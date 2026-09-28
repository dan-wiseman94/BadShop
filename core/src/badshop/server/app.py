"""CoreApp: the headless core behind the local API (spec 5.6, 7).

It owns the open session, the tool executor, the approval gate and the agent turn. JSON-RPC methods
become session calls; session changes become events for every subscriber. No sockets here:
server/ws.py (Task 13) connects clients and calls `dispatcher.handle`, `subscribe` and
`on_client_gone`."""

import asyncio
import base64
import binascii
import io
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from badshop import files
from badshop.agent import approval
from badshop.agent.approval import ApprovalGate
from badshop.agent.fake import ScriptedProvider
from badshop.agent.loop import TurnConfig, run_turn
from badshop.engine import assets, manifest
from badshop.engine.common import fit, has_alpha, to_rgb
from badshop.engine.errors import EngineError
from badshop.server import rpc
from badshop.server.rpc import INVALID_PARAMS, Dispatcher, RpcError
from badshop.server.settings import ApprovalMode, Settings, load_settings, save_settings
from badshop.session import project
from badshop.session.execution import Executor
from badshop.session.models import Step
from badshop.session.session import RUNNABLE, Session
from badshop.session.worker import WorkerExecutor
from badshop.tools import REGISTRY, registry, runner

log = logging.getLogger("badshop.server")

Send = Callable[[str], Awaitable[None]]
SessionName = Annotated[str, Field(min_length=1, max_length=200)]
MaxPx = Annotated[int, Field(ge=16, le=4096)]
Verdict = Literal["approve", "reject", "edit"]
MAX_IMPORT_BYTES = 200 * 2**20  # a picked file bigger than this is refused before it is read
NO_PROVIDER_HINT = "set fake_provider_script in the settings (or BADSHOP_FAKE_PROVIDER) to a script file"


def _user_path(path: str) -> Path:
    """A path the user picked in a file dialog. Relative paths would depend on the core's working
    folder, so they are refused."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise EngineError(f"{path} is not an absolute path", hint="pick the file with the file dialog")
    return p


def _read_import(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_IMPORT_BYTES:
            raise EngineError(f"{path.name} is too big to import",
                              hint=f"the limit is {MAX_IMPORT_BYTES // 2**20} MB; use a smaller copy")
        return path.read_bytes()
    except OSError as e:
        raise EngineError(f"can't read {path} ({e.strerror or e})",
                          hint="check that the file exists and is readable") from None


def _write_json(path: Path, value: Any) -> None:
    try:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise EngineError(f"can't write {path} ({e.strerror or e})",
                          hint="check that the folder exists and is writable") from None


def _artifact_payload(session: Session, ref: str, max_px: int | None) -> dict:
    """The artifact's stored bytes, or (with max_px) a PNG no bigger than max_px on its longest side."""
    store = session.artifacts
    aid = store.resolve(ref)
    meta = store.meta[aid]
    if max_px is None:
        data, mime = store.data(aid), meta.mime
    else:
        im = store.image(aid)
        small, _ = fit(im.convert("RGBA") if has_alpha(im) else to_rgb(im), max_px)
        buf = io.BytesIO()
        small.save(buf, "PNG")
        data, mime = buf.getvalue(), "image/png"
    return {"meta": meta.model_dump(mode="json"), "mime": mime,
            "data": base64.b64encode(data).decode("ascii")}


def _tool_entry(spec: registry.ToolSpec, trusted: bool) -> dict:
    return {"name": spec.name, "summary": spec.summary, "description": spec.description,
            "category": spec.category, "mutates": spec.mutates, "network": spec.network,
            "read_only": spec.read_only, "writes_files": spec.writes_files,
            "schema": registry.ui_schema(spec) if trusted else registry.llm_schema(spec)}


class CoreApp:
    """Create it inside the running event loop (it binds to that loop), and `await close()` when done."""

    def __init__(self, settings: Settings | None = None,
                 executor_factory: Callable[..., Executor] = WorkerExecutor):
        self._loop = asyncio.get_running_loop()
        self.settings = settings if settings is not None else load_settings()
        # The last run's autosave, moved aside before this run can autosave over it: the restore offer
        # (spec 9, 10) that session.get reports and session.restore takes.
        self._restorable = self._claim_autosave()
        self._executor_factory = executor_factory
        self._executor = self._new_executor()
        self._lock = asyncio.Lock()  # one session call (and so one tool) at a time
        self._subscribers: dict[asyncio.Queue, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()  # background work (auto replays, cleanups)
        self._turn: asyncio.Task | None = None
        self._turn_cfg: TurnConfig | None = None
        self._switching = 0  # session.new / session.open calls under way: no turn may start meanwhile
        self._provider: ScriptedProvider | None = None
        self._dirty = False  # the session changed since the last autosave
        self._closed = False
        # Two gates: the in-app turn's (Stop cancels it) and the CLI agents' (only a closed UI, a new or
        # opened session, or close() cancels it). Both check an edit's image ids against the open session.
        self.gate = ApprovalGate(self._emit, resolve=self._resolve_ref)
        self._cli_gate = ApprovalGate(self._emit, resolve=self._resolve_ref)
        self.path: Path | None = None  # the project file the session was opened from or saved to
        self.session = self._new_session("Untitled")
        self._dirty = False  # nothing autosaves until the session changes: an untouched core leaves none
        self._prev_progress = assets.PROGRESS
        assets.PROGRESS = self._on_progress
        self.dispatcher = Dispatcher()
        self._register()

    # --- plumbing -------------------------------------------------------------------------------

    def _new_executor(self) -> Executor:
        return self._executor_factory(timeout_s=self.settings.tool_timeout_s,
                                      max_rss_mb=self.settings.tool_memory_mb)

    def _output_dir(self) -> Path:
        chosen = self.settings.output_dir
        return Path(chosen).expanduser() if chosen else files.default_output_dir()

    def _session_kw(self) -> dict:
        return {"executor": self._executor, "emit": self._emit, "output_dir": self._output_dir(),
                "on_change": self._changed}

    def _new_session(self, name: str) -> Session:
        session = Session.new(name, **self._session_kw())
        session.data.approval_mode = self.settings.approval_mode
        return session

    def _changed(self) -> None:  # Session.on_change: called from whichever thread changed it
        self._dirty = True

    def _resolve_ref(self, ref: str) -> str:  # the gates' check of an edit's image ids (thread-safe, no disk)
        return self.session.artifacts.resolve(ref)

    def _log(self, level: str, message: str) -> None:
        self._emit("core.log", {"level": level, "message": message})

    @staticmethod
    def _claim_autosave() -> Path | None:
        """Keep the last run's autosave for the restore offer. claim_autosave never raises (a file it can't
        move stays for the next launch); should it ever, that only costs the offer: it is logged (no client
        is connected yet) and the core starts anyway."""
        try:
            return project.claim_autosave()
        except (EngineError, OSError) as e:
            log.warning("can't keep the last autosave to offer restoring it: %s", getattr(e, "message", e))
            return None

    def _autosave(self) -> None:
        """Runs in a worker thread under the lock. A failed autosave is reported, never raised."""
        if not self._dirty:
            return
        self._dirty = False
        try:
            project.autosave(self.session)
        except (EngineError, OSError) as e:
            self._log("warning", f"autosave failed: {getattr(e, 'message', e)}")

    async def _blocking(self, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
        """Run a session call in a thread, one at a time, then autosave if anything changed. This is
        the `blocking` run_turn gets. A thread can't be interrupted, so if the caller is cancelled the
        lock is held until the thread ends, and only then does the cancellation go on: the lock is never
        released while a thread is inside the session. (run_turn's Stop stops its step's tool through
        that step's own cancel event, even while the call still waits here for the lock; close() calls
        the executor's cancel() for any other call.)"""
        def work() -> Any:
            try:
                return fn(*args, **kw)
            finally:
                self._autosave()

        async with self._lock:
            fut = asyncio.ensure_future(asyncio.to_thread(work))
            try:
                return await asyncio.shield(fut)
            except asyncio.CancelledError:
                while not fut.done():
                    try:
                        await asyncio.wait({fut})
                    except asyncio.CancelledError:
                        pass
                if not fut.cancelled():
                    fut.exception()  # mark it retrieved: the caller is gone, so is its result
                raise

    def _emit(self, method: str, params: dict) -> None:
        """Queue an event for every subscriber. Callable from any thread (session calls run in threads)."""
        msg = rpc.notification(method, params)
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        if here is self._loop:
            self._deliver(msg)
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, msg)
        except RuntimeError:  # the loop is closed: nobody is listening any more
            pass

    def _deliver(self, msg: str) -> None:
        for queue in self._subscribers:
            queue.put_nowait(msg)

    async def _pump(self, queue: asyncio.Queue, send: Send) -> None:
        """Send one subscriber its events in order; a failed send drops the subscriber."""
        while True:
            msg = await queue.get()
            try:
                await send(msg)
            except Exception:
                log.debug("dropping a subscriber whose send failed", exc_info=True)
                self._subscribers.pop(queue, None)
                return

    def subscribe(self, send: Send) -> Callable[[], None]:
        """Receive every event (a JSON-RPC notification string) through `send`, in order. Returns the
        function that unsubscribes."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        pump = self._loop.create_task(self._pump(queue, send))
        self._subscribers[queue] = pump

        def unsubscribe() -> None:
            if self._subscribers.pop(queue, None) is not None:
                pump.cancel()

        return unsubscribe

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        task = self._loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _on_progress(self, name: str, done: int, total: int | None) -> None:  # assets.PROGRESS
        self._emit("asset.progress", {"name": name, "done": done, "total": total})

    def _snapshot(self) -> dict:
        """The session as saved (SessionData by alias) plus what the app knows about it."""
        return {**self.session.data.model_dump(mode="json", by_alias=True),
                "path": str(self.path) if self.path else None,
                "turn_running": self._turn is not None,
                "pending_approvals": self.gate.pending() + self._cli_gate.pending(),
                "restorable": str(self._restorable) if self._restorable else None}

    def _check_idle(self) -> None:
        if self._turn is not None:
            raise EngineError("the agent is still working", hint="press Stop, or wait for the turn to finish")

    def _cancel_approvals(self, note: str) -> None:
        """Reject every step waiting for approval, the turn's and the CLI agents'."""
        self.gate.cancel_all(note)
        self._cli_gate.cancel_all(note)

    def _get_provider(self) -> ScriptedProvider:
        if self._provider is None:
            path = self.settings.fake_provider_script or os.environ.get("BADSHOP_FAKE_PROVIDER")
            if not path:
                raise EngineError("no model provider is set up yet", hint=NO_PROVIDER_HINT)
            self._provider = ScriptedProvider.from_file(Path(path))  # a bad script is its own EngineError
        return self._provider

    # --- the agent turn -------------------------------------------------------------------------

    async def _turn_main(self, session: Session, provider: ScriptedProvider, text: str,
                         attachments: list[str], cfg: TurnConfig) -> None:
        finished = False  # run_turn announced the end itself

        def emit(method: str, params: dict) -> None:
            nonlocal finished
            finished = finished or method == "turn.finished"
            self._emit(method, params)

        try:
            await run_turn(session, provider, self.gate, text, attachments, cfg, emit,
                           blocking=self._blocking)
        except asyncio.CancelledError:  # stopped
            if not finished:
                self._emit("turn.finished", {"reason": "stopped"})
        except Exception as e:  # the turn broke: say so, and keep the core serving
            log.exception("the agent turn failed")
            self._log("error", f"the agent turn failed ({type(e).__name__}: {e})")
            if not finished:
                self._emit("turn.finished", {"reason": "error", "error": f"{type(e).__name__}: {e}"})
        finally:
            self._turn = self._turn_cfg = None
        await self._blocking(self._changed)  # one autosave of the session as the turn left it

    async def _stop_turn(self, note: str) -> bool:
        """Cancel the running turn and wait for it to end. run_turn rejects the steps it left waiting
        (Task 11), and `_reject_waiting` makes sure: a stopped turn never leaves a step "proposed". CLI
        agents' calls are not the turn's and keep waiting. False if no turn was running."""
        task, session = self._turn, self.session
        if task is None:
            return False
        task.cancel()
        await asyncio.wait({task})
        if self._turn is task:  # cancelled before it ever ran: its own cleanup never happened
            self._turn = self._turn_cfg = None
            self._emit("turn.finished", {"reason": "stopped"})
        await self._blocking(self._reject_waiting, session, note)
        return True

    @staticmethod
    def _reject_waiting(session: Session, note: str) -> None:
        """The safety net behind run_turn's own wind-up: an agent step still proposed is rejected. Under
        the lock, so two stops at once (a closed client, then close()) reject each step once."""
        for step in list(session.data.steps):
            if step.status == "proposed" and step.actor.startswith("agent:"):
                session.reject(step.id, note)

    def on_client_gone(self) -> None:
        """The last user client disconnected: stop the agent's turn and reject every pending approval
        (a CLI agent's too), so nothing waits for a user who isn't there. The core keeps serving, and
        the next client sees the session as it was left."""
        self._cancel_approvals("the user closed the app")
        if self._turn is not None:
            self._spawn(self._stop_turn("the user closed the app"))

    async def close(self) -> None:
        """Stop the turn and background work, autosave, close the executor, drop the subscribers."""
        if self._closed:
            return
        self._closed = True
        self._cancel_approvals("badshop is closing")
        await self._stop_turn("badshop is closing")
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        self._executor.cancel()  # kill a tool a replay is running; nothing runs on this executor again
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._blocking(lambda: None)  # a last autosave, if anything changed
        await asyncio.to_thread(self._executor.close)
        pumps = list(self._subscribers.values())
        self._subscribers.clear()
        for pump in pumps:
            pump.cancel()
        await asyncio.gather(*pumps, return_exceptions=True)
        if assets.PROGRESS == self._on_progress:
            assets.PROGRESS = self._prev_progress

    # --- methods: session -----------------------------------------------------------------------

    def _register(self) -> None:
        for name, handler, actors in (
            ("session.new", self._session_new, "user"),
            ("session.get", self._session_get, "user"),
            ("session.open", self._session_open, "user"),
            ("session.restore", self._session_restore, "user"),
            ("session.save", self._session_save, "user"),
            ("session.save_as", self._session_save_as, "user"),
            ("session.export_recipe", self._session_export_recipe, "user"),
            ("session.set_approval_mode", self._session_set_approval_mode, "user"),
            ("chat.send", self._chat_send, "user"),
            ("chat.stop", self._chat_stop, "user"),
            ("tools.list", self._tools_list, "any"),
            ("tools.run", self._tools_run, "any"),
            ("steps.edit", self._steps_edit, "user"),
            ("steps.replay_from", self._steps_replay_from, "user"),
            ("steps.delete", self._steps_delete, "user"),
            ("approval.respond", self._approval_respond, "user"),
            ("artifacts.get", self._artifacts_get, "any"),
            ("artifacts.import", self._artifacts_import, "user"),
            ("export", self._export, "user"),
            ("settings.get", self._settings_get, "user"),
            ("settings.set", self._settings_set, "user"),
            ("assets.status", self._assets_status, "user"),
            ("assets.download", self._assets_download, "user"),
        ):
            self.dispatcher.method(name, actors=actors)(handler)

    async def _switch(self, replace: Callable[[], None], note: str) -> dict:
        """session.new, session.open and session.restore: `replace` swaps the session in, under the lock.
        From the idle check until the swap is done no turn can start (chat.send refuses while `_switching`),
        so a turn never runs on a session that is being replaced; `replace` checks again under the lock. CLI
        calls still waiting for approval belong to the old session: they are rejected once it is gone, even
        when the caller of this method was cancelled (a swap whose thread has started always finishes; one
        cancelled while it waits for the lock never starts, and then nothing changes)."""
        self._check_idle()
        before = self.session
        self._switching += 1
        try:
            await self._blocking(replace)
        finally:
            self._switching -= 1
            if self.session is not before:
                self._cancel_approvals(note)
        return self._snapshot()

    async def _session_new(self, actor: str, name: SessionName = "Untitled") -> dict:
        def replace() -> None:
            self._check_idle()
            self.session, self.path = self._new_session(name), None
            self._dirty = True

        return await self._switch(replace, "the user started a new session")

    async def _session_get(self, actor: str) -> dict:
        return self._snapshot()

    async def _session_open(self, actor: str, path: str) -> dict:
        p = _user_path(path)

        def load() -> None:
            self._check_idle()
            session = project.open_project(p, **self._session_kw())  # any failure: the session is untouched
            # a file in the autosave folder is badshop's, not the user's project: Save must not write there
            autosaved = p.resolve().parent == project.autosave_path().parent.resolve()
            self.session, self.path = session, None if autosaved else p
            self._dirty = True

        return await self._switch(load, "the user opened another session")

    async def _session_restore(self, actor: str) -> dict:
        """Open the last run's autosave (the offer the snapshot's `restorable` names) as an unsaved
        session. Taking the offer uses it up; a failed restore changes nothing."""
        def load() -> None:
            self._check_idle()
            if self._restorable is None:
                raise EngineError("there is no autosaved session to restore",
                                  hint="the last run left no autosaved session, or it was restored already")
            session = project.open_project(self._restorable, **self._session_kw())
            self.session, self.path, self._restorable = session, None, None
            self._dirty = True  # autosaved at once: from now on this run's autosave holds it

        return await self._switch(load, "the user restored the autosaved session")

    async def _session_save(self, actor: str) -> dict:
        def save() -> Path:
            if self.path is None:
                raise EngineError("this session has no project file yet", hint="use Save As to pick one")
            return project.save(self.session, self.path)

        return {"path": str(await self._blocking(save))}

    async def _session_save_as(self, actor: str, path: str) -> dict:
        p = _user_path(path)

        def save() -> Path:
            self.path = project.save(self.session, p)
            return self.path

        return {"path": str(await self._blocking(save))}

    async def _session_export_recipe(self, actor: str, path: str) -> dict:
        p = _user_path(path)
        await self._blocking(lambda: _write_json(p, project.export_recipe(self.session)))
        return {"path": str(p)}

    async def _session_set_approval_mode(self, actor: str, mode: ApprovalMode) -> dict:
        def apply() -> None:
            self.session.data.approval_mode = mode
            self._dirty = True

        await self._blocking(apply)
        if self._turn_cfg is not None:  # the running turn follows the switch from its next tool call
            self._turn_cfg.approval_mode = mode
        return self._snapshot()

    # --- methods: chat --------------------------------------------------------------------------

    async def _chat_send(self, actor: str, text: str, attachments: list[str] | None = None) -> dict:
        self._check_idle()
        if self._switching:
            raise EngineError("the session is being replaced", hint="send the message again once it has opened")
        provider = self._get_provider()
        session = self.session
        ids = [session.artifacts.resolve(a) for a in attachments or []]  # a bad ref fails now, not mid-turn
        cfg = TurnConfig(approval_mode=session.data.approval_mode, step_budget=self.settings.step_budget)
        self._turn_cfg = cfg
        self._turn = self._spawn(self._turn_main(session, provider, text, ids, cfg))
        return {"started": True}

    async def _chat_stop(self, actor: str) -> dict:
        return {"stopped": await self._stop_turn("stopped by the user")}

    # --- methods: tools and steps ---------------------------------------------------------------

    async def _tools_list(self, actor: str) -> list[dict]:
        trusted = runner.is_trusted(actor)
        return [_tool_entry(spec, trusted) for spec in REGISTRY.values()]

    async def _tools_run(self, actor: str, tool: str, params: dict | None = None) -> dict:
        """The user's tools run at once. Any other actor's call is proposed, then waits for the approval
        the session's mode asks for (spec 7), exactly like the in-app agent's calls."""
        raw = params or {}
        if runner.is_trusted(actor):
            step = await self._blocking(lambda: self.session.run_tool(tool, raw, actor))
            return step.model_dump(mode="json")
        return await self._cli_call(actor, tool, raw)

    async def _cli_call(self, actor: str, tool: str, raw: dict) -> dict:
        """A CLI agent's call: proposed as that actor (so the session applies the untrusted rules), then it
        waits in the CLI gate, then it runs. However it ends, its step never stays waiting: a rejection or
        an edit the session refuses rejects it, and so does a caller that stops waiting (Task 13 cancels a
        closed connection's requests). chat.stop never touches it: Stop is about the in-app turn."""
        got: dict[str, Any] = {}

        def propose() -> Step:
            got["session"] = self.session  # read under the lock: the session the step really went into
            got["step"] = self.session.propose(tool, raw, actor)
            return got["step"]

        try:
            step = await self._blocking(propose)
            session, edited = got["session"], None
            if approval.needs_approval(registry.get(tool), session.data.approval_mode):
                decision = await self._cli_gate.request(step)
                if decision.decision == "reject":
                    step = await self._blocking(self._settle, session, step.id, decision.note)
                    return step.model_dump(mode="json")
                edited = decision.params if decision.decision == "edit" else None
            step = await self._blocking(self._run_or_reject, session, step.id, edited)
            return step.model_dump(mode="json")
        except asyncio.CancelledError:
            if "step" in got:  # proposed, and maybe still waiting: settle it before letting go
                await self._blocking(self._settle, got["session"], got["step"].id, "the agent stopped waiting")
            raise

    @staticmethod
    def _settle(session: Session, step_id: str, note: str | None) -> Step:
        """Reject a step that is still waiting to run; one that ran or was rejected already stays as it is."""
        step = session.step(step_id)
        return session.reject(step_id, note) if step.status in RUNNABLE else step

    @staticmethod
    def _run_or_reject(session: Session, step_id: str, params: dict | None) -> Step:
        """Run an approved (or user-edited) CLI step, with the fallback in the same locked call. The gate
        already checks an edit (valid as the user's, image ids in the session); should `Session.run` still
        refuse one, it does so before it changes the step, which would leave the step `proposed` with
        nothing waiting for it. It is rejected instead, as Task 11's `_execute` does for the in-app turn."""
        try:
            return session.run(step_id, params)
        except EngineError as e:
            if params is None:  # a proposed step runs on its own params: nothing to fall back to
                raise
            return session.reject(step_id, f"the edited parameters were refused: {e.message}")

    async def _steps_edit(self, actor: str, step_id: str, params: dict) -> dict:
        def edit() -> tuple[Session, list[Step]]:
            return self.session, self.session.edit(step_id, params)

        session, stale = await self._blocking(edit)
        if self.settings.auto_replay and stale:
            self._spawn(self._auto_replay(session, step_id))
        return {"stale": [s.id for s in stale]}

    async def _auto_replay(self, session: Session, step_id: str) -> None:
        try:
            await self._blocking(lambda: session.replay_from(step_id) if session is self.session else [])
        except Exception as e:  # nobody awaits this task: report instead of raising
            log.exception("auto replay failed")
            self._log("warning", f"replay failed: {getattr(e, 'message', e)}")

    async def _steps_replay_from(self, actor: str, step_id: str) -> list[dict]:
        steps = await self._blocking(lambda: self.session.replay_from(step_id))
        return [s.model_dump(mode="json") for s in steps]

    async def _steps_delete(self, actor: str, step_id: str) -> dict:
        await self._blocking(lambda: self.session.delete_last(step_id))
        return {"deleted": step_id}

    async def _approval_respond(self, actor: str, step_id: str, decision: Verdict, params: dict | None = None,
                                note: str | None = None) -> dict:
        # The gate checks an edit (valid as the user's, image ids in the session): a bad one is an
        # EngineError and the step waits on. A step in neither gate is the turn gate's clean EngineError.
        gate = self._cli_gate if step_id in self._cli_gate.pending() else self.gate
        gate.respond(step_id, decision, params, note)
        return {"ok": True}

    # --- methods: artifacts and files -----------------------------------------------------------

    async def _artifacts_get(self, actor: str, id: str, max_px: MaxPx | None = None) -> dict:
        # Artifacts are immutable, so reading one needs no lock: the viewer stays live while a tool runs.
        return await asyncio.to_thread(_artifact_payload, self.session, id, max_px)

    async def _artifacts_import(self, actor: str, path: str | None = None, data: str | None = None,
                                name: str | None = None) -> dict:
        if (path is None) == (data is None):
            raise RpcError(INVALID_PARAMS, "give either path or data",
                           {"hint": "path: a file the user picked; data: the image bytes in base64"})
        if path is not None:
            p = _user_path(path)
            blob = await asyncio.to_thread(_read_import, p)
            label = name or p.name
        else:
            try:
                blob = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise RpcError(INVALID_PARAMS, "data is not base64") from None
            label = name or ""

        def do() -> tuple:  # the store turns a file name into a label ("pasted" when there is none)
            working = self.session.import_image(blob, label)
            return working, self.session.artifacts.meta.get(working.original_id or "", working)

        working, original = await self._blocking(do)
        return {"working": working.model_dump(mode="json"), "original": original.model_dump(mode="json")}

    async def _export(self, actor: str, artifact_id: str, name: str | None = None) -> dict:
        path = await self._blocking(lambda: self.session.export(artifact_id, name))
        return {"path": str(path)}

    # --- methods: settings and assets -----------------------------------------------------------

    async def _settings_get(self, actor: str) -> dict:
        return self.settings.model_dump(mode="json")

    async def _settings_set(self, actor: str, values: dict) -> dict:
        try:
            new = Settings.model_validate({**self.settings.model_dump(), **values})
        except ValidationError as e:
            raise RpcError(INVALID_PARAMS, "invalid settings", {"hint": runner.explain(e)}) from None
        await self._blocking(self._apply_settings, new)
        return new.model_dump(mode="json")

    def _apply_settings(self, new: Settings) -> None:
        """Runs in a thread under the lock, so no tool is running while the executor is swapped."""
        save_settings(new)
        old, self.settings = self.settings, new
        if (new.tool_timeout_s, new.tool_memory_mb) != (old.tool_timeout_s, old.tool_memory_mb):
            retired, self._executor = self._executor, self._new_executor()
            self.session.executor = self._executor
            retired.close()
        self.session.output_dir = self._output_dir()
        if new.fake_provider_script != old.fake_provider_script:
            self._provider = None

    async def _assets_status(self, actor: str) -> list[dict]:
        return await asyncio.to_thread(manifest.status)

    async def _assets_download(self, actor: str, name: str) -> dict:
        # Not under the lock: a 170 MB model download must not hold up tools. Progress arrives as
        # asset.progress events through assets.PROGRESS.
        return {"path": str(await asyncio.to_thread(manifest.download, name))}
