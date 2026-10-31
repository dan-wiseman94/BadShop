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
import threading
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from badshop import files
from badshop.agent import approval
from badshop.agent.approval import ApprovalGate
from badshop.agent.fake import ScriptedProvider
from badshop.agent.provider import Provider, ProviderError
from badshop.providers import profiles
from badshop.providers.litellm_provider import LiteLLMProvider, close_clients
from badshop.providers.cli_provider import CLIProvider, discover_clis, inspect_cli
from badshop.providers.cli_turn import run_cli_turn
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
DocumentRevision = Annotated[int, Field(strict=True, ge=0)]
DiscardUnsaved = Annotated[bool, Field(strict=True)]
MaxPx = Annotated[int, Field(ge=16, le=4096)]
Verdict = Literal["approve", "reject", "edit"]
MAX_IMPORT_BYTES = 200 * 2**20  # a picked file bigger than this is refused before it is read
NO_PROVIDER_HINT = "add a profile with providers.save and select it with providers.select, or use badshop chat --model"


def _user_path(path: str) -> Path:
    """A path the user picked in a file dialog. Relative paths would depend on the core's working
    folder, so they are refused, and so is "~name/..." for a user this computer doesn't have."""
    try:
        p: Path | None = Path(path).expanduser()
    except RuntimeError:  # pathlib can't find that user's home folder
        p = None
    if p is None or not p.is_absolute():
        raise EngineError(f"{path} is not an absolute path", hint="pick the file with the file dialog")
    return p


def _in_autosave_folder(p: Path) -> bool:
    """A file there is badshop's, never the user's project: the next launch's claim_autosave moves the
    autosave aside. Touches the disk (it resolves links), so it runs in a worker thread."""
    try:
        return p.resolve().parent == project.autosave_path().parent.resolve()
    except (OSError, RuntimeError):  # a symlink loop (Python 3.12 raises RuntimeError): not that folder
        return False


def _too_big(name: str) -> EngineError:
    return EngineError(f"{name} is too big to import",
                       hint=f"the limit is {MAX_IMPORT_BYTES // 2**20} MB; use a smaller copy")


def _read_import(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_IMPORT_BYTES:
            raise _too_big(path.name)
        return path.read_bytes()
    except OSError as e:
        raise EngineError(f"can't read {path} ({e.strerror or e})",
                          hint="check that the file exists and is readable") from None


def _pasted_size(data: str) -> int:
    """The bytes valid base64 `data` decodes to, known from its length alone (the padding comes off)."""
    return len(data) * 3 // 4 - data[-2:].count("=")


def _decode_paste(data: str) -> bytes:
    """Pasted image bytes. Runs in a worker thread: a big paste must not stall the event loop."""
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise RpcError(INVALID_PARAMS, "data is not base64") from None


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
            "cli_positionals": list(spec.params.POSITIONAL), "cli_flags": spec.params.FLAGS,
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
        self._starting = False  # a provider/keychain lookup reserved the next turn
        self._start_generation = 0  # Stop invalidates a lookup even before _turn exists
        self._turn_cfg: TurnConfig | None = None
        self._switching = 0  # session.new / session.open calls under way: no turn may start meanwhile
        self._provider: Provider | None = None
        self._connection: tuple[str, str] | None = None
        self._cli_providers: dict[tuple[str, str], CLIProvider] = {}
        self._retired_clis: list[CLIProvider] = []
        self._cli_turn_actor: str | None = None
        self._cli_message_id: str | None = None
        self._cli_remaining: int | None = None
        self._cli_cancels: dict[str, threading.Event] = {}
        self._retry_session: Session | None = None
        self._profiles_error: EngineError | None = None
        try:
            self._profiles = profiles.load_profiles()
        except EngineError as e:
            self._profiles, self._profiles_error = {}, e
            log.warning("provider profiles could not be loaded; tools and sessions remain available")
        self._dirty = False  # the session changed since the last autosave
        # Autosave is recovery, not a user Save. Revisions never repeat during this core's lifetime,
        # including when a saved session id is opened again, so dialogs can safely guard replacement.
        self._document_revision = 0
        self._saved_revision = 0
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
        self._downloads: dict[str, tuple[threading.Event, asyncio.Task]] = {}
        self._prev_cancel = assets.CANCEL
        assets.CANCEL = self._download_cancelled
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
        """What every session is made with; `_own` gives it its emit once it exists."""
        return {"executor": self._executor, "output_dir": self._output_dir(), "on_change": self._changed}

    def _own(self, session: Session) -> Session:
        """Forward events and changes only while this is the open session. Step ids start at s1 in every session and
        events carry no session id, so what a replaced session still does (a waiting CLI step it rejects
        after session.open, say) must not reach a client: it would land on the new session's step."""
        def emit(method: str, params: dict) -> None:
            if self.session is session:
                self._emit(method, params)

        def changed() -> None:
            if getattr(self, "session", None) is session:
                self._changed()

        session.emit = emit
        session.on_change = changed
        return session

    def _new_session(self, name: str) -> Session:
        session = self._own(Session.new(name, **self._session_kw()))
        session.data.approval_mode = self.settings.approval_mode
        return session

    def _changed(self) -> None:  # Session.on_change: called from whichever thread changed it
        self._document_revision += 1
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
                "document_revision": self._document_revision,
                "unsaved_changes": self._document_revision != self._saved_revision,
                "turn_running": self._turn is not None or self._starting,
                "pending_approvals": self.gate.pending() + self._cli_gate.pending(),
                "restorable": str(self._restorable) if self._restorable else None}

    def _check_idle(self) -> None:
        if self._closed:
            raise EngineError("badshop is closing")
        if self._turn is not None or self._starting:
            raise EngineError("the agent is still working", hint="press Stop, or wait for the turn to finish")

    def _check_revision(self, expected_revision: int | None, operation: str) -> None:
        """Called under the session lock, immediately before a guarded replacement or file write."""
        if expected_revision is not None and expected_revision != self._document_revision:
            raise EngineError(f"the session changed before it could be {operation}",
                              hint="review the latest changes and try again")

    def _cancel_approvals(self, note: str) -> None:
        """Reject every step waiting for approval, the turn's and the CLI agents'."""
        self.gate.cancel_all(note)
        self._cli_gate.cancel_all(note)

    def _get_provider(self) -> Provider:
        profile_id = self.session.data.provider_profile_id
        if profile_id:
            profile = self._profile(profile_id)
            return self._make_provider(profile)
        if self._provider is None:
            path = self.settings.fake_provider_script or os.environ.get("BADSHOP_FAKE_PROVIDER")
            if not path:
                raise EngineError("no model provider is set up yet", hint=NO_PROVIDER_HINT)
            self._provider = ScriptedProvider.from_file(Path(path))
        return self._provider

    def _check_profiles(self) -> None:
        if self._profiles_error is not None:
            raise self._profiles_error

    def _profile(self, profile_id: str) -> profiles.Profile:
        self._check_profiles()
        if profile_id not in self._profiles:
            raise EngineError("provider profile not found", hint="select an existing profile or add one")
        return self._profiles[profile_id]

    def set_connection(self, url: str, token: str) -> None:
        """The listener supplies its loopback address before CLI providers may launch MCP proxies."""
        from badshop.diagnostics import register_secret
        register_secret(token)
        self._connection = (url, token)

    def _make_provider(self, profile: profiles.Profile) -> LiteLLMProvider | CLIProvider:
        if profile.kind == "cli":
            if self._connection is None:
                raise EngineError("the local core connection is not ready")
            key = (self.session.data.id, profile.id)
            cached = self._cli_providers.get(key)
            if cached and cached.profile == profile:
                return cached
            provider = CLIProvider(profile, *self._connection)
            if cached:
                self._retired_clis.append(cached)
            self._cli_providers[key] = provider
            return provider
        return LiteLLMProvider(profile.model, api_base=profile.api_base,
                              api_key=profiles.resolve_key(profile), actor=f"agent:{profile.id}",
                              capability_overrides=profile.capability_overrides)

    # --- the agent turn -------------------------------------------------------------------------

    async def _turn_main(self, session: Session, provider: Provider, text: str,
                         attachments: list[str], cfg: TurnConfig, retry: bool = False) -> None:
        finished = False  # run_turn announced the end itself

        def emit(method: str, params: dict) -> None:
            nonlocal finished
            finished = finished or method == "turn.finished"
            if method == "turn.finished":
                self._retry_session = session if params.get("reason") == "provider_error" else None
                self._emit("provider.status", {"profile_id": session.data.provider_profile_id,
                                               "status": "error" if self._retry_session else "ready",
                                               "error": params.get("error")})
            self._emit(method, params)
            if method == "turn.started":
                self._emit("provider.status", {"profile_id": session.data.provider_profile_id, "status": "busy"})

        try:
            if isinstance(provider, CLIProvider):
                await run_cli_turn(self, session, provider, text, attachments, cfg, emit, retry=retry)
            else:
                await run_turn(session, provider, self.gate, text, attachments, cfg, emit,
                               blocking=self._blocking, retry=retry)
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
        await self._blocking(session.on_change)  # the old turn must never dirty a replacement session

    async def _stop_turn(self, note: str) -> bool:
        """Cancel the running turn and wait for it to end. run_turn rejects the steps it left waiting
        (Task 11), and `_reject_waiting` makes sure: a stopped turn never leaves a step "proposed". CLI
        agents' calls are not the turn's and keep waiting. False if no turn was running."""
        starting = self._starting
        self._start_generation += 1  # pending provider setup must never start after Stop
        task, session, cli_actor = self._turn, self.session, self._cli_turn_actor
        if task is None:
            return starting
        if self._cli_turn_actor:
            for step_id, cancel in self._cli_cancels.items():
                if session.step(step_id).actor == cli_actor:
                    cancel.set()
        task.cancel()
        await asyncio.wait({task})
        if self._turn is task:  # cancelled before it ever ran: its own cleanup never happened
            self._turn = self._turn_cfg = None
            self._emit("turn.finished", {"reason": "stopped"})
        await self._blocking(self._reject_waiting, session, note, cli_actor)
        return True

    @staticmethod
    def _reject_waiting(session: Session, note: str, cli_actor: str | None = None) -> None:
        """The safety net behind run_turn's own wind-up: an agent step still proposed is rejected. Under
        the lock, so two stops at once (a closed client, then close()) reject each step once."""
        for step in list(session.data.steps):
            if step.status == "proposed" and (step.actor.startswith("agent:") or step.actor == cli_actor):
                session.reject(step.id, note)

    def on_client_gone(self) -> None:
        """The last user client disconnected: stop the agent's turn and reject every pending approval
        (a CLI agent's too), so nothing waits for a user who isn't there. The core keeps serving, and
        the next client sees the session as it was left."""
        self._cancel_approvals("the user closed the app")
        for signal, _ in self._downloads.values():
            signal.set()
        self._start_generation += 1  # also invalidate sends still queued for _lock
        if self._turn is not None or self._starting:
            self._spawn(self._stop_turn("the user closed the app"))

    async def close(self) -> None:
        """Stop the turn and background work, autosave, close the executor, drop the subscribers."""
        if self._closed:
            return
        self._closed = True
        downloads = list(self._downloads.values())
        for signal, _ in downloads:
            signal.set()
        self._cancel_approvals("badshop is closing")
        await self._stop_turn("badshop is closing")
        await asyncio.gather(*(p.close() for p in [*self._cli_providers.values(), *self._retired_clis]),
                             return_exceptions=True)
        self._cli_providers.clear()
        self._retired_clis.clear()
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
        await asyncio.gather(*(task for _, task in downloads), return_exceptions=True)
        if assets.PROGRESS == self._on_progress:
            assets.PROGRESS = self._prev_progress
        if assets.CANCEL == self._download_cancelled:
            assets.CANCEL = self._prev_cancel
        await close_clients()

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
            ("chat.retry", self._chat_retry, "user"),
            ("providers.list", self._providers_list, "user"),
            ("providers.save", self._providers_save, "user"),
            ("providers.add", self._providers_save, "user"),
            ("providers.delete", self._providers_delete, "user"),
            ("providers.select", self._providers_select, "user"),
            ("providers.test", self._providers_test, "user"),
            ("providers.detect", self._providers_detect, "user"),
            ("diagnostics.get", self._diagnostics_get, "user"),
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
            ("assets.cancel", self._assets_cancel, "user"),
        ):
            self.dispatcher.method(name, actors=actors)(handler)

    async def _switch(self, replace: Callable[[], None], note: str,
                      expected_revision: int | None = None, discard_unsaved: bool = False) -> dict:
        """session.new, session.open and session.restore: `replace` swaps the session in, under the lock.
        From the idle check until the swap is done no turn can start (chat.send refuses while `_switching`),
        so a turn never runs on a session that is being replaced; `replace` checks again under the lock. CLI
        calls still waiting for approval belong to the old session: they are rejected once it is gone, even
        when the caller of this method was cancelled (a swap whose thread has started always finishes; one
        cancelled while it waits for the lock never starts, and then nothing changes)."""
        self._check_idle()
        replaced = False

        def guarded_replace() -> None:
            nonlocal replaced
            self._check_idle()
            # Legacy clients omit the token. Desktop clients opt into both checks; they run after
            # any queued mutation, before loading files, swapping sessions, or cancelling approvals.
            if expected_revision is not None:
                self._check_revision(expected_revision, "replaced")
                if self._document_revision != self._saved_revision and not discard_unsaved:
                    raise EngineError("the session has unsaved changes",
                                      hint="Save the project or explicitly discard its changes")
            before = self.session
            try:
                replace()
            finally:
                replaced = self.session is not before

        self._switching += 1
        try:
            await self._blocking(guarded_replace)
        finally:
            self._switching -= 1
            if replaced:
                self._cancel_approvals(note)
                for key, provider in list(self._cli_providers.items()):
                    if key[0] != self.session.data.id:
                        self._cli_providers.pop(key)
                        await provider.close()
        return self._snapshot()

    async def _session_new(self, actor: str, name: SessionName = "Untitled",
                           expected_revision: DocumentRevision | None = None,
                           discard_unsaved: DiscardUnsaved = False) -> dict:
        def replace() -> None:
            self._check_idle()
            self.session, self.path = self._new_session(name), None
            self._changed()
            self._saved_revision = self._document_revision

        return await self._switch(replace, "the user started a new session", expected_revision, discard_unsaved)

    async def _session_get(self, actor: str) -> dict:
        return self._snapshot()

    async def _session_open(self, actor: str, path: str, expected_revision: DocumentRevision | None = None,
                            discard_unsaved: DiscardUnsaved = False) -> dict:
        p = _user_path(path)

        def load() -> None:
            self._check_idle()
            session = project.open_project(p, **self._session_kw())  # any failure: the session is untouched
            # a file in the autosave folder is badshop's, not the user's project: Save must not write there
            self.session, self.path = self._own(session), None if _in_autosave_folder(p) else p
            self._changed()
            self._saved_revision = self._document_revision

        return await self._switch(load, "the user opened another session", expected_revision, discard_unsaved)

    async def _session_restore(self, actor: str, expected_revision: DocumentRevision | None = None,
                               discard_unsaved: DiscardUnsaved = False) -> dict:
        """Open the last run's autosave (the offer the snapshot's `restorable` names) as an unsaved
        session. Taking the offer uses it up; a failed restore changes nothing."""
        def load() -> None:
            self._check_idle()
            if self._restorable is None:
                raise EngineError("there is no autosaved session to restore",
                                  hint="the last run left no autosaved session, or it was restored already")
            session = project.open_project(self._restorable, **self._session_kw())
            self.session, self.path, self._restorable = self._own(session), None, None
            self._changed()  # recovery is unsaved; from now on this run's autosave holds it

        return await self._switch(load, "the user restored the autosaved session", expected_revision, discard_unsaved)

    async def _session_save(self, actor: str, expected_revision: DocumentRevision | None = None) -> dict:
        def save() -> Path:
            self._check_revision(expected_revision, "saved")
            if self.path is None:
                raise EngineError("this session has no project file yet", hint="use Save As to pick one")
            saved = project.save(self.session, self.path)
            self._saved_revision = self._document_revision
            return saved

        return {"path": str(await self._blocking(save))}

    async def _session_save_as(self, actor: str, path: str,
                               expected_revision: DocumentRevision | None = None) -> dict:
        p = _user_path(path)

        def save() -> Path:
            self._check_revision(expected_revision, "saved")
            if _in_autosave_folder(p):  # the next launch would move the "project" out of the user's way
                folder = project.autosave_path().parent
                raise EngineError(f"can't save a project in {folder}: it is badshop's autosave folder",
                                  hint="pick another folder for the project")
            self.path = project.save(self.session, p)
            self._saved_revision = self._document_revision
            return self.path

        return {"path": str(await self._blocking(save))}

    async def _session_export_recipe(self, actor: str, path: str) -> dict:
        p = _user_path(path)
        await self._blocking(lambda: _write_json(p, project.export_recipe(self.session)))
        return {"path": str(p)}

    async def _session_set_approval_mode(self, actor: str, mode: ApprovalMode) -> dict:
        def apply() -> None:
            self.session.data.approval_mode = mode
            self._changed()

        await self._blocking(apply)
        if self._turn_cfg is not None:  # the running turn follows the switch from its next tool call
            self._turn_cfg.approval_mode = mode
        return self._snapshot()

    # --- methods: chat --------------------------------------------------------------------------

    async def _chat_send(self, actor: str, text: str, attachments: list[str] | None = None) -> dict:
        self._check_idle()
        if self._switching:
            raise EngineError("the session is being replaced", hint="send the message again once it has opened")
        # Keep start atomic with provider/session changes, including while keyring is unlocking.
        generation = self._start_generation
        async with self._lock:
            self._check_idle()
            if self._switching:
                raise EngineError("the session is being replaced")
            if generation != self._start_generation:
                raise EngineError("the provider start was stopped")
            return await self._prepare_turn(text, attachments or [])

    async def _prepare_turn(self, text: str, attachments: list[str], *, retry: bool = False) -> dict:
        """Called with _lock held. Reserve setup so Stop also covers a slow keychain unlock.

        A cancelled request must hold the lock until its lookup thread finishes: loading a fake
        provider writes _provider, and releasing early would let it overwrite newer settings.
        """
        self._starting = True
        self._start_generation += 1
        generation = self._start_generation
        future = asyncio.ensure_future(asyncio.to_thread(self._get_provider))
        try:
            try:
                provider = await asyncio.shield(future)
            except asyncio.CancelledError:
                while not future.done():
                    try:
                        await asyncio.wait({future})
                    except asyncio.CancelledError:
                        pass
                if not future.cancelled():
                    future.exception()
                raise
            if self._closed or generation != self._start_generation:
                raise EngineError("the provider start was stopped")
            if self._switching:
                raise EngineError("the session is being replaced")
            return self._start_turn(provider, text, attachments, retry=retry)
        finally:
            self._starting = False

    def _start_turn(self, provider: Provider, text: str, attachments: list[str], *, retry: bool = False) -> dict:
        session = self.session
        ids = [session.artifacts.resolve(a) for a in attachments or []]  # a bad ref fails now, not mid-turn
        cfg = TurnConfig(approval_mode=session.data.approval_mode, step_budget=self.settings.step_budget)
        self._turn_cfg = cfg
        self._retry_session = None
        self._turn = self._spawn(self._turn_main(session, provider, text, ids, cfg, retry))
        return {"started": True}

    async def _chat_retry(self, actor: str) -> dict:
        generation = self._start_generation
        async with self._lock:
            self._check_idle()
            if self._switching or self._retry_session is not self.session:
                raise EngineError("there is no failed provider turn to retry")
            if generation != self._start_generation:
                raise EngineError("the provider start was stopped")
            return await self._prepare_turn("", [], retry=True)

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
            if actor == self._cli_turn_actor and self._cli_remaining is not None:
                if self._cli_remaining <= 0:
                    raise EngineError("this turn's tool budget is used up", hint="ask the user to continue")
                self._cli_remaining -= 1
            got["session"] = self.session  # read under the lock: the session the step really went into
            got["step"] = self.session.propose(tool, raw, actor)
            if actor == self._cli_turn_actor and self._cli_message_id:
                message = next((m for m in self.session.data.messages if m.id == self._cli_message_id), None)
                if message:
                    message.step_ids.append(got["step"].id)
                    self._emit("message.done", {"message": message.model_dump(mode="json")})
            got["cancel"] = threading.Event()
            self._cli_cancels[got["step"].id] = got["cancel"]
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
            task = asyncio.create_task(self._blocking(self._run_or_reject, session, step.id, edited, got["cancel"]))
            got["task"] = task
            step = await asyncio.shield(task)
            return step.model_dump(mode="json")
        except asyncio.CancelledError:
            if "cancel" in got:
                got["cancel"].set()
            if "task" in got:
                await asyncio.shield(got["task"])
            if "step" in got:  # proposed, and maybe still waiting: settle it before letting go
                await self._blocking(self._settle, got["session"], got["step"].id, "the agent stopped waiting")
            raise
        finally:
            if "step" in got:
                self._cli_cancels.pop(got["step"].id, None)

    @staticmethod
    def _settle(session: Session, step_id: str, note: str | None) -> Step:
        """Reject a step that is still waiting to run; one that ran or was rejected already stays as it is."""
        step = session.step(step_id)
        return session.reject(step_id, note) if step.status in RUNNABLE else step

    @staticmethod
    def _run_or_reject(session: Session, step_id: str, params: dict | None,
                       cancel: threading.Event | None = None) -> Step:
        """Run an approved (or user-edited) CLI step, with the fallback in the same locked call. The gate
        already checks an edit (valid as the user's, image ids in the session); should `Session.run` still
        refuse one, it does so before it changes the step, which would leave the step `proposed` with
        nothing waiting for it. It is rejected instead, as Task 11's `_execute` does for the in-app turn."""
        try:
            return session.run(step_id, params, cancel=cancel)
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

    async def _steps_replay_from(self, actor: str, step_id: str, use_cache: bool = True) -> list[dict]:
        # use_cache=False runs every step again, even one whose inputs did not change (spec 2, criterion 4)
        steps = await self._blocking(lambda: self.session.replay_from(step_id, use_cache=use_cache))
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
        blob: bytes | None = None
        if path is not None:
            p = _user_path(path)
            blob = await asyncio.to_thread(_read_import, p)
            label = name or p.name
        elif _pasted_size(data) > MAX_IMPORT_BYTES:  # the path's limit, refused before anything is decoded
            raise _too_big(name or "the pasted image")
        else:
            label = name or ""

        def do() -> tuple:  # the store turns a file name into a label ("pasted" when there is none)
            working = self.session.import_image(_decode_paste(data) if blob is None else blob, label)
            return working, self.session.artifacts.meta.get(working.original_id or "", working)

        working, original = await self._blocking(do)
        return {"working": working.model_dump(mode="json"), "original": original.model_dump(mode="json")}

    async def _export(self, actor: str, artifact_id: str, name: str | None = None) -> dict:
        path = await self._blocking(lambda: self.session.export(artifact_id, name))
        return {"path": str(path)}

    # --- methods: providers -------------------------------------------------------------------

    def _cleanup_key(self, key_ref: str) -> None:
        try:
            profiles.delete_key(key_ref)
        except EngineError:
            self._log("warning", "an unused provider key could not be removed from the OS keychain")

    async def _providers_list(self, actor: str) -> list[dict]:
        self._check_profiles()
        return [p.model_dump(mode="json") for p in self._profiles.values()]

    async def _providers_save(self, actor: str, profile: dict, api_key: str | None = None) -> dict:
        def save() -> dict:
            self._check_idle()
            self._check_profiles()
            p = profiles.parse_profile(profile)
            if p.kind == "cli" and api_key is not None:
                raise EngineError("CLI profiles use the CLI's own subscription login")
            old = self._profiles.get(p.id)
            if p.api_key_ref is not None and (old is None or p.api_key_ref != old.api_key_ref):
                raise EngineError("a profile cannot reference another provider's key")
            new_ref = None
            if api_key is not None:
                if not api_key.strip():
                    raise EngineError("the API key must not be empty")
                # Write a new key slot so a failed config write cannot replace the working credential.
                new_ref = f"{p.id}:{uuid.uuid4().hex}"
                profiles.store_key(new_ref, api_key)
                p = p.model_copy(update={"api_key_ref": new_ref, "api_key_env": None})
            elif p.kind != "cli" and old and old.api_key_ref and not p.api_key_env:
                p = p.model_copy(update={"api_key_ref": old.api_key_ref})
            if p.api_key_env:
                p = p.model_copy(update={"api_key_ref": None})
            updated = {**self._profiles, p.id: p}
            try:
                profiles.save_profiles(updated)
            except EngineError:
                if new_ref:
                    self._cleanup_key(new_ref)
                raise
            self._profiles = updated
            if old and old.api_key_ref and old.api_key_ref != p.api_key_ref:
                self._cleanup_key(old.api_key_ref)
            return p.model_dump(mode="json")
        return await self._blocking(save)

    async def _providers_select(self, actor: str, profile_id: str) -> dict:
        def select() -> None:
            self._check_idle()
            self._profile(profile_id)
            self.session.data.provider_profile_id = profile_id
            self._changed()
        await self._blocking(select)
        self._emit("provider.status", {"profile_id": profile_id, "status": "selected"})
        return self._snapshot()

    async def _providers_delete(self, actor: str, profile_id: str) -> dict:
        def delete() -> None:
            self._check_idle()
            p = self._profile(profile_id)
            updated = {k: v for k, v in self._profiles.items() if k != profile_id}
            profiles.save_profiles(updated)
            self._profiles = updated
            if p.api_key_ref:
                self._cleanup_key(p.api_key_ref)
            if self.session.data.provider_profile_id == profile_id:
                self.session.data.provider_profile_id = None
                self._changed()
        await self._blocking(delete)
        return {"deleted": True}

    async def _providers_test(self, actor: str, profile_id: str, probe: bool = False) -> dict:
        # Capability inspection is offline. A paid test completion requires probe=true.
        try:
            profile = self._profile(profile_id)
            if profile.kind == "cli":
                info = await asyncio.to_thread(inspect_cli, profile.cli, profile.executable)
                result = {"profile_id": profile_id, "status": "ready" if info["supported"] else "error",
                          **info, "capabilities": {"vision": True, "tool_calls": True}, "probed": False,
                          "warnings": ["Gemini CLI support is experimental"] if profile.cli == "gemini" else []}
                self._emit("provider.status", result)
                return result
            provider = await self._blocking(lambda: self._make_provider(self._profile(profile_id)))
            capabilities = await asyncio.to_thread(provider.check_capabilities)
            if probe:
                await provider.complete([{"role": "user", "content": "Reply with OK."}], [], lambda _: None)
            result = {"profile_id": profile_id, "status": "ready", "capabilities": capabilities,
                      "probed": probe, "warnings": getattr(provider, "warnings", [])}
        except (ProviderError, EngineError) as e:
            result = {"profile_id": profile_id, "status": "error", "error": str(e)}
        self._emit("provider.status", result)
        return result

    async def _providers_detect(self, actor: str) -> list[dict]:
        return await asyncio.to_thread(discover_clis)

    async def _diagnostics_get(self, actor: str) -> dict:
        from badshop.diagnostics import diagnostic_report
        return await asyncio.to_thread(diagnostic_report)

    # --- methods: settings and assets -----------------------------------------------------------

    async def _settings_get(self, actor: str) -> dict:
        return self.settings.model_dump(mode="json")

    async def _settings_set(self, actor: str, values: dict) -> dict:
        return (await self._blocking(self._apply_settings, values)).model_dump(mode="json")

    def _apply_settings(self, values: dict) -> Settings:
        """Runs in a thread under the lock, so no tool is running while the executor is swapped, and the
        values merge into the settings as they are now: changes queued behind a running tool apply in
        order and none is lost."""
        try:
            new = Settings.model_validate({**self.settings.model_dump(), **values})
        except ValidationError as e:
            raise RpcError(INVALID_PARAMS, "invalid settings", {"hint": runner.explain(e)}) from None
        save_settings(new)
        old, self.settings = self.settings, new
        if (new.tool_timeout_s, new.tool_memory_mb) != (old.tool_timeout_s, old.tool_memory_mb):
            retired, self._executor = self._executor, self._new_executor()
            self.session.executor = self._executor
            retired.close()
        self.session.output_dir = self._output_dir()
        if new.fake_provider_script != old.fake_provider_script:
            self._provider = None
        return new

    async def _assets_status(self, actor: str) -> list[dict]:
        return await asyncio.to_thread(manifest.status)

    async def _assets_download(self, actor: str, name: str) -> dict:
        # Not under the lock: a 170 MB model download must not hold up tools. Progress arrives as
        # asset.progress events through assets.PROGRESS.
        manifest.get_asset(name)
        if self._closed:
            raise EngineError("badshop is closing")
        if name in self._downloads:
            raise EngineError("this asset is already downloading")
        signal = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(manifest.download, name))
        self._downloads[name] = (signal, task)

        def finished(done: asyncio.Task) -> None:
            self._downloads.pop(name, None)
            if not done.cancelled():
                done.exception()  # observe a failure even if the requesting socket has gone away

        task.add_done_callback(finished)
        try:
            return {"path": str(await asyncio.shield(task))}
        except asyncio.CancelledError:
            signal.set()  # cancelling an asyncio waiter cannot interrupt its worker thread
            raise

    def _download_cancelled(self, name: str) -> bool:
        pending = self._downloads.get(name)
        return bool(pending and pending[0].is_set())

    async def _assets_cancel(self, actor: str, name: str) -> dict:
        pending = self._downloads.get(name)
        active = pending is not None and not pending[1].done()
        if active:
            pending[0].set()
        return {"cancelled": active}
