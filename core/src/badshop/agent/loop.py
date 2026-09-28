"""One agent turn (spec §5.4): ask the model, run its tool calls through the session with approvals,
feed the results back, and repeat until it answers without calls, the user stops it, the step budget
runs out, or it keeps making invalid calls."""

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from badshop.agent.approval import ApprovalGate, needs_approval
from badshop.agent.context import build_messages, image_placeholder, tool_definitions
from badshop.agent.provider import Provider, ProviderError, Reply, ToolCallRequest
from badshop.engine.errors import EngineError
from badshop.session.models import ArtifactMeta, Message, Part, Step
from badshop.session.session import RUNNABLE, Emit, Session
from badshop.tools import registry

Blocking = Callable[..., Awaitable[Any]]  # asyncio.to_thread, or the server's locked version of it

STOPPED = "stopped by the user"
FAILED = "the turn failed"
CHANGES_NOTE = "Since your last turn the user changed the session (the step list is current):"


@dataclass
class TurnConfig:
    approval_mode: str = "ask_changes"  # read at every call: the server can switch it mid-turn
    step_budget: int = 40  # executed steps per turn
    max_invalid: int = 3  # consecutive invalid calls end the turn


def _arguments(call: ToolCallRequest) -> dict:
    args = call.arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, RecursionError):  # deep nesting ("[[[[..." to the token limit) is RecursionError
            raise EngineError(f"the arguments for {call.name} are not valid JSON",
                              hint="send the arguments as one JSON object") from None
    if not isinstance(args, dict):
        raise EngineError(f"the arguments for {call.name} must be a JSON object",
                          hint="send the arguments as one JSON object")
    return args


def _error_text(e: EngineError) -> str:
    return f"error: {e.message}" + (f"\nhint: {e.hint}" if e.hint else "")


def _openai_call(call: ToolCallRequest) -> dict:
    args = call.arguments if isinstance(call.arguments, str) else json.dumps(call.arguments)
    return {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": args}}


# The functions below run through `blocking` (a worker thread), like every other session call.

def _attachments(session: Session, refs: list[str]) -> list[ArtifactMeta]:
    return [session.artifacts.meta[session.artifacts.resolve(r)] for r in refs]


def _record(session: Session, *entries: dict) -> None:
    """Append to the provider-format transcript. It is session state like any other, so the autosave
    hook hears of it: a restored session never has a call whose answer was only in memory."""
    session.data.transcript.extend(entries)
    session.on_change()


def _changes_note(session: Session) -> Message | None:
    """The user's changes since the agent's last turn as one system note, taken, recorded and added to the
    chat in one call: a Stop that lands while it runs can't lose them (spec 5.3)."""
    changes = session.take_changes()
    if not changes:
        return None
    note = "\n".join([CHANGES_NOTE, *(f"- {c}" for c in changes)])
    _record(session, {"role": "system", "content": note})
    return session.add_message("system_note", [Part(type="text", text=note)])


def _find(session: Session, step_id: str) -> Step | None:
    """The step, or None when the user deleted it (Session.step would raise)."""
    return next((s for s in session.data.steps if s.id == step_id), None)


def _as_it_is(step: Step) -> str:
    """The answer for a call whose step something other than this turn settled while it waited: how it
    ended (a run's result, a rejection and its note), or what it is now."""
    if step.status in ("done", "error", "rejected") and step.result_text:
        return step.result_text
    return f"not run: the user changed this step (it is {step.status} now)"


def _propose(session: Session, message_id: str, tool: str, raw: dict, actor: str,
             reason: str | None) -> tuple[Step, dict | None]:
    """Propose the call as a step of the reply's message. Returns the step and the message as JSON, now
    listing it (dumped here, under the caller's lock)."""
    step = session.propose(tool, raw, actor, reason)
    message = next((m for m in session.data.messages if m.id == message_id), None)
    if message is None:
        return step, None
    message.step_ids.append(step.id)
    session.on_change()
    return step, message.model_dump(mode="json")


def _reject(session: Session, step_id: str, note: str) -> str:
    """Carry out the user's rejection. Returns what the model hears back."""
    step = _find(session, step_id)
    if step is None:
        return "not run: the user deleted this step"
    if step.status not in RUNNABLE:  # settled elsewhere while it waited: answer with what happened
        return _as_it_is(step)
    session.reject(step_id, note)
    return f"rejected by user: {note}"


def _execute(session: Session, step_id: str, params: dict | None,
             cancel: threading.Event) -> tuple[bool, str]:
    """Run an approved (or user-edited) step, with `cancel` as its stop signal. Returns whether a tool ran,
    and what the model hears back."""
    step = _find(session, step_id)
    if step is None:
        return False, "not run: the user deleted this step"
    if step.status not in RUNNABLE:  # settled elsewhere while it waited: answer with what happened
        return False, _as_it_is(step)
    try:
        step = session.run(step_id, params, cancel=cancel)
    except EngineError as e:
        if params is None:  # a proposed step on its own params always runs: a bug, and the turn says so
            raise
        # The user's edit didn't resolve (an image id that isn't in the session, from a gate without
        # `resolve`). run() checks before it changes anything, so the step is still waiting: reject it.
        session.reject(step_id, f"the edited parameters were refused: {e.message}")
        return False, f"rejected by user: their edited parameters were refused ({e.message})"
    text = step.result_text  # the session's own report of the run: outputs, the tool's lines, or the error
    if params is not None:
        text = f"the user edited the parameters before it ran: {json.dumps(step.params)}\n{text}"
    return True, text


def _wind_up(session: Session, message_id: str | None, unanswered: dict[str, str | None], note: str) -> None:
    """After Stop (or a failure): reject the steps this turn left waiting, and answer every call left
    without a result, so the transcript stays one a provider accepts. Only steps still `proposed` or
    `approved` are rejected; a step something else settled is answered as it is, a deleted one as deleted,
    and nothing here raises over a step that changed or is gone."""
    message = next((m for m in session.data.messages if m.id == message_id), None)
    ours = [*(message.step_ids if message else []), *(s for s in unanswered.values() if s)]
    stopped = set()
    for step_id in dict.fromkeys(ours):
        step = _find(session, step_id)
        if step is not None and step.status in RUNNABLE:
            session.reject(step_id, note)
            stopped.add(step_id)
    entries = []
    for call_id, step_id in unanswered.items():
        step = _find(session, step_id) if step_id else None
        if step_id is None or step_id in stopped:
            content = f"not run: {note}"
        elif step is None:  # it finished, then the user deleted it, before this turn could answer
            content = "the user deleted this step"
        else:
            content = _as_it_is(step)  # a result that came in as Stop landed, or a step settled elsewhere
        entries.append({"role": "tool", "tool_call_id": call_id, "content": content})
    if entries:
        _record(session, *entries)


async def _to_the_end(aw: Awaitable[None]) -> None:
    """Finish the wind-up even if the turn is cancelled again (chat.stop, then the client going away;
    on_client_gone, then close()), then pass that cancellation on."""
    task = asyncio.ensure_future(aw)
    again = False
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            again = True
    task.result()
    if again:
        raise asyncio.CancelledError


class _Turn:
    def __init__(self, session: Session, provider: Provider, gate: ApprovalGate, cfg: TurnConfig,
                 emit: Emit, blocking: Blocking):
        self.session, self.provider, self.gate, self.cfg = session, provider, gate, cfg
        self.emit, self.blocking = emit, blocking
        self.executed = 0  # steps run this turn (the budget)
        self.invalid = 0  # consecutive invalid calls
        self.message_id: str | None = None  # the assistant message of the reply being handled
        self.unanswered: dict[str, str | None] = {}  # its call ids without a result -> their step ids
        self.inflight: asyncio.Task | None = None  # the session call under way
        self.stopping: threading.Event | None = None  # the executing step's own stop signal: Stop sets it
        self.error: str | None = None  # the provider's error message

    async def call(self, fn: Callable, *args: Any) -> Any:
        """`fn(*args)` through `blocking`, shielded from cancellation: Stop waits for it to end rather
        than abandon a thread halfway through changing the session."""
        self.inflight = asyncio.ensure_future(self.blocking(fn, *args))
        result = await asyncio.shield(self.inflight)
        self.inflight = None
        return result

    async def message(self, role: str, parts: list[Part]) -> str:
        m = await self.call(self.session.add_message, role, parts)
        self.emit("message.done", {"message": m.model_dump(mode="json")})
        return m.id

    async def answer(self, call_id: str, content: str) -> None:
        self.unanswered.pop(call_id, None)  # before recording: Stop must never answer a call twice
        await self.call(_record, self.session, {"role": "tool", "tool_call_id": call_id, "content": content})

    async def answer_rest(self, content: str) -> None:
        for call_id in list(self.unanswered):
            await self.answer(call_id, content)

    def delta(self, chunk: str) -> None:
        self.emit("message.delta", {"text": chunk})

    async def run(self, text: str, images: list[ArtifactMeta]) -> str:
        note = await self.call(_changes_note, self.session)
        if note is not None:
            self.emit("message.done", {"message": note.model_dump(mode="json")})
        lines = ([text] if text else []) + [image_placeholder(m) for m in images]
        await self.call(_record, self.session, {"role": "user", "content": "\n".join(lines)})
        await self.message("user", ([Part(type="text", text=text)] if text else [])
                           + [Part(type="image", artifact_id=m.id) for m in images])
        tools = tool_definitions()
        while True:
            messages = await self.call(build_messages, self.session)
            try:
                reply = await self.provider.complete(messages, tools, self.delta)
            except ProviderError as e:
                self.error = str(e)
                return "provider_error"
            reason = await self.handle(reply)
            if reason:
                return reason

    async def handle(self, reply: Reply) -> str | None:
        entry: dict = {"role": "assistant", "content": reply.text}
        if reply.tool_calls:  # OpenAI's shape: content may be null when the reply only calls tools
            entry.update(content=reply.text or None, tool_calls=[_openai_call(c) for c in reply.tool_calls])
        self.unanswered = {c.id: None for c in reply.tool_calls}
        await self.call(_record, self.session, entry)
        self.message_id = await self.message("assistant",
                                             [Part(type="text", text=reply.text)] if reply.text else [])
        if not reply.tool_calls:
            return "done"
        why = reply.text.strip()[:500] or None  # the model's stated reason, shown on approval cards
        for call in reply.tool_calls:
            if self.executed >= self.cfg.step_budget:
                await self.answer_rest(f"not run: this turn's budget of {self.cfg.step_budget} steps is used "
                                       "up; the user can send a message to continue")
                return "budget"
            await self.handle_call(call, why)
            if self.invalid >= self.cfg.max_invalid:
                await self.answer_rest(f"not run: {self.cfg.max_invalid} invalid calls in a row ended the "
                                       "turn")
                return "invalid_calls"
        return None

    async def handle_call(self, call: ToolCallRequest, why: str | None) -> None:
        try:
            spec = registry.get(call.name)
            args = _arguments(call)
            step, message = await self.call(_propose, self.session, self.message_id, call.name, args,
                                            self.provider.actor, why)
        except EngineError as e:  # bad JSON, unknown tool, bad or user-only parameters, unknown artifact
            self.invalid += 1
            await self.answer(call.id, _error_text(e))
            return
        self.invalid = 0
        self.unanswered[call.id] = step.id
        if message is not None:  # the reply again, now listing the step: clients upsert messages by id
            self.emit("message.done", {"message": message})
        params = None
        if needs_approval(spec, self.cfg.approval_mode):
            decision = await self.gate.request(step)
            if decision.decision == "reject":
                content = await self.call(_reject, self.session, step.id, decision.note or "no reason given")
                await self.answer(call.id, content)
                return
            params = decision.params if decision.decision == "edit" else None
        self.stopping = threading.Event()  # one per step: it goes with this call and no other
        ran, content = await self.call(_execute, self.session, step.id, params, self.stopping)
        self.stopping = None
        if ran:
            self.executed += 1
        await self.answer(call.id, content)

    async def stop(self, note: str) -> None:
        """Stop mid-turn: reject waiting approvals, stop the step being executed, let the session call under
        way finish, then leave the session and its transcript consistent."""
        self.gate.cancel_all(note)
        if self.stopping is not None:  # this step's call only, whether or not it has reached the executor
            self.stopping.set()
        if self.inflight is not None:
            await asyncio.wait([self.inflight])  # a stopped tool ends at once; its step records how it ended
        await self.blocking(_wind_up, self.session, self.message_id, dict(self.unanswered), note)


async def run_turn(session: Session, provider: Provider, gate: ApprovalGate, text: str,
                   attachments: list[str], cfg: TurnConfig, emit: Emit,
                   blocking: Blocking = asyncio.to_thread) -> str:
    """Run one turn and return why it ended: "done", "budget", "invalid_calls" or "provider_error".

    Stop is cancelling the task that runs this: pending approvals are rejected, a running tool is killed,
    `turn.finished {"reason": "stopped"}` is emitted and CancelledError propagates. Any other exception
    ends the turn with `turn.finished {"reason": "error"}` and propagates. A cancel that lands while the
    turn winds up (a second Stop, or a Stop on a failing turn) waits for the wind-up to end, then
    propagates. An attachment that doesn't resolve raises EngineError before anything is recorded or
    emitted."""
    images = await blocking(_attachments, session, attachments)
    turn = _Turn(session, provider, gate, cfg, emit, blocking)
    emit("turn.started", {})
    try:
        reason = await turn.run(text, images)
    except asyncio.CancelledError:
        try:
            await _to_the_end(turn.stop(STOPPED))
        finally:
            emit("turn.finished", {"reason": "stopped"})
        raise
    except Exception as e:
        try:
            await _to_the_end(turn.stop(FAILED))
        finally:
            emit("turn.finished", {"reason": "error", "error": f"{type(e).__name__}: {e}"})
        raise
    emit("turn.finished", {"reason": reason, **({"error": turn.error} if turn.error else {})})
    return reason
