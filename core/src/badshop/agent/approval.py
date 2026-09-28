"""Approve-before-run (spec §7): which calls wait for the user, and the gate where they wait.

The gate lives on the event loop: `request` is awaited by the agent loop, `respond` and `cancel_all` are
called from the same loop (a client's `approval.respond`, Stop, or the last client going away)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from badshop.engine.errors import EngineError
from badshop.session.models import Step
from badshop.session.session import Emit
from badshop.tools.registry import ToolSpec, image_fields
from badshop.tools.runner import validate

MODES = ("auto", "ask_changes", "ask_all")
DECISIONS = ("approve", "reject", "edit")


def needs_approval(spec: ToolSpec, mode: str) -> bool:
    """auto: nothing waits. ask_changes: only read-only tools (find, info, view) run unasked; export, which
    writes a file but changes no image, waits like any other change. ask_all: everything waits."""
    if mode not in MODES:
        raise EngineError(f"unknown approval mode {mode!r}", hint=f"use one of: {', '.join(MODES)}")
    if mode == "auto":
        return False
    if mode == "ask_changes":
        return not spec.read_only
    return True


@dataclass
class Decision:
    decision: Literal["approve", "reject", "edit"]
    params: dict | None = None  # the user's parameters, for "edit"
    note: str | None = None  # why, for "reject"; the model hears it


class ApprovalGate:
    def __init__(self, emit: Emit, resolve: Callable[[str], str] | None = None):
        """`resolve` turns an image ref into a full artifact id or raises EngineError (the server passes the
        current session's `artifacts.resolve`, which never touches the disk and is safe to call while a
        tool runs). With it, an edit naming an image the session doesn't have is refused here and the step
        keeps waiting; without it, the session refuses that edit when the step runs."""
        self._emit, self._resolve = emit, resolve
        self._waiting: dict[str, tuple[Step, asyncio.Future]] = {}

    async def request(self, step: Step) -> Decision:
        """Announce the step and wait for the user's decision. If the waiting turn is cancelled, the entry
        stays until cancel_all() resolves and announces it."""
        fut = asyncio.get_running_loop().create_future()
        self._waiting[step.id] = (step, fut)
        self._emit("approval.needed", {"step": step.model_dump(mode="json")})
        return await fut

    def respond(self, step_id: str, decision: str, params: dict | None = None,
                note: str | None = None) -> None:
        """Resolve a waiting step. Edited parameters are validated here, as the user's, and their image refs
        checked when the gate has `resolve`: a bad edit raises EngineError and the step keeps waiting."""
        entry = self._waiting.get(step_id)
        if entry is None or entry[1].done():
            raise EngineError(f"step {step_id} is not waiting for approval",
                              hint="it was already decided, or its turn was stopped")
        step, fut = entry
        if decision not in DECISIONS:
            raise EngineError(f"unknown decision {decision!r}", hint=f"use one of: {', '.join(DECISIONS)}")
        if decision == "edit":
            if not isinstance(params, dict):
                raise EngineError("an edit needs the new parameters", hint="send params with the edit")
            checked = validate(step.tool, params, "user")
            if self._resolve is not None:
                dumped = checked.model_dump(mode="json")
                for name, is_list in image_fields(type(checked)).items():
                    value = dumped.get(name)
                    for ref in (value if is_list else [value]) if value is not None else []:
                        self._resolve(ref)  # EngineError "no such artifact: <ref>"
        elif params is not None:
            raise EngineError(f"parameters go with decision 'edit', not {decision!r}",
                              hint="send decision 'edit' to run the step with changed parameters")
        del self._waiting[step_id]
        fut.set_result(Decision(decision, params, note))
        self._emit("approval.resolved", {"step_id": step_id, "decision": decision, "note": note})

    def pending(self) -> list[str]:
        return [step_id for step_id, (_, fut) in self._waiting.items() if not fut.done()]

    def cancel_all(self, note: str = "the user closed the app") -> None:
        """Reject every waiting step (Stop, or no client left to answer)."""
        waiting, self._waiting = self._waiting, {}
        for step_id, (_, fut) in waiting.items():
            if not fut.done():
                fut.set_result(Decision("reject", note=note))
            self._emit("approval.resolved", {"step_id": step_id, "decision": "reject", "note": note})
