"""Independent timelines sharing a project's immutable artifact store.

Switching snapshots the outgoing direction first: a switch is an edit to one document, never a
request to discard it. Saving that document includes all snapshots and their referenced artifacts.
"""

import time
import uuid
from contextlib import contextmanager

from badshop.engine.errors import EngineError
from badshop.session.models import BranchSnapshot
from badshop.session.history import capture

MAX_AUTOMATIC_BRANCHES = 10  # five recent before/after turn pairs; named directions are never pruned


def _snapshot(session, id: str, name: str, created_at: float, automatic: bool = False) -> BranchSnapshot:
    revision = capture(session.data.history_nodes, {
        'steps': [step.model_dump(mode='json') for step in session.data.steps],
        'messages': [message.model_dump(mode='json') for message in session.data.messages],
        'transcript': session.data.transcript,
    })
    return BranchSnapshot(id=id, name=name, created_at=created_at, automatic=automatic, revision=revision,
                          max_step_number=max((int(sid[1:]) for sid in (
                              [step.id for step in session.data.steps]
                              + [sid for message in session.data.messages for sid in message.step_ids])), default=0),
                          max_message_number=max((int(message.id[1:]) for message in session.data.messages), default=0),
                          creative=session.data.creative.model_copy(deep=True),
                          artifact_ids=sorted(session.visible_artifact_ids()))


def _remember(session) -> None:
    active = session.data.active_branch_id
    if active is None:
        active = uuid.uuid4().hex
        session.data.branches[active] = _snapshot(session, active, "Original", time.time())
        session.data.active_branch_id = active
    else:
        old = session.data.branches[active]
        session.data.branches[active] = _snapshot(session, active, old.name, old.created_at, old.automatic)


def listing(session) -> dict:
    active = session.data.active_branch_id
    rows = []
    for branch in session.data.branches.values():
        steps = session.data.steps if branch.id == active else session.data.branch_state(branch).steps
        preview = next((s.outputs[0] for s in reversed(steps) if s.status == "done" and s.outputs), None)
        rows.append({"id": branch.id, "name": branch.name, "created_at": branch.created_at,
                     "step_count": len(steps), "preview_id": preview})
    return {"active_id": active, "branches": rows}


def _idle(session) -> None:
    if any(step.status in ("proposed", "approved", "running") for step in session.data.steps):
        raise EngineError("finish or reject pending steps before changing directions")


def create(session, name: str, from_step: str | None = None, *, automatic: bool = False) -> None:
    _idle(session)
    index = None
    if from_step is not None:
        target = session.step(from_step)
        if target.status != "done":
            raise EngineError("choose a finished step to branch from")
        index = session.data.steps.index(target)
    _remember(session)
    id = uuid.uuid4().hex
    branch = _snapshot(session, id, name, time.time(), automatic)
    if index is not None:
        state = session.data.branch_state(branch)
        removed = {s.id for s in state.steps[index + 1:]}
        state.steps = state.steps[:index + 1]
        branch.artifact_ids = [aid for aid in branch.artifact_ids
                               if session.artifacts.meta[aid].produced_by not in removed]
        kept = {s.id for s in state.steps}
        # A conversation after the cut may describe images no longer in this direction. Start a fresh
        # transcript and retain only self-contained user inputs and messages about retained steps.
        last_kept_message = max((i for i, m in enumerate(state.messages)
                                 if m.step_ids and set(m.step_ids) <= kept), default=-1)
        state.messages = [m for m in state.messages[:last_kept_message + 1]
                           if not m.step_ids or set(m.step_ids) <= kept]
        state.transcript = []
        session.data.set_branch_state(branch, state)
    session.data.branches[id] = branch
    _activate(session, branch)


def _activate(session, branch: BranchSnapshot, *, clear_history: bool = True) -> None:
    if clear_history:
        session.data.manual_undo.clear()
        session.data.manual_redo.clear()
    session.data.active_branch_id = branch.id
    state = session.data.branch_state(branch)
    session.data.steps = state.steps
    session.data.messages = state.messages
    session.data.creative = branch.creative.model_copy(deep=True)
    # CLI processes are retired by CoreApp, API conversations are rebuilt with the new timeline.
    session.data.transcript = state.transcript
    session.data.collect_history()
    session.changes = [f"the user switched to creative direction {branch.name!r}; use its current timeline"]
    session._changed()


def switch(session, id: str) -> None:
    _idle(session)
    if id not in session.data.branches:
        raise EngineError("no such creative direction")
    if id == session.data.active_branch_id:
        return
    session.data.branches[id].automatic = False  # explicitly choosing a direction retains it
    _remember(session)
    _activate(session, session.data.branches[id])
    if id == session.data.undo_branch_id:
        create(session, "Checkpoint edits")


def rename(session, id: str, name: str) -> dict:
    if id not in session.data.branches:
        raise EngineError("no such creative direction")
    session.data.branches[id].name = name
    session.data.branches[id].automatic = False
    session._changed()
    return listing(session)


def remove(session, id: str) -> dict:
    if id == session.data.undo_branch_id:
        raise EngineError("this direction is the last AI turn's undo checkpoint")
    if id == session.data.active_branch_id:
        raise EngineError("switch to another direction before removing this one")
    if id not in session.data.branches:
        raise EngineError("no such creative direction")
    del session.data.branches[id]
    session.data.collect_history()
    session._changed()
    return listing(session)


def begin_turn(session) -> None:
    """Preserve the current direction and give this turn its own recoverable branch."""
    session.data.manual_undo.clear()
    session.data.manual_redo.clear()
    if any(step.status in ("proposed", "approved", "running") for step in session.data.steps):
        session.data.undo_branch_id = None
        session.changes.append("turn undo is unavailable while another caller owns a pending step")
        session._changed()
        return
    _idle(session)
    changes = list(session.changes)
    create(session, "Before AI turn", automatic=True)
    checkpoint = session.data.active_branch_id
    create(session, "AI turn", automatic=True)
    session.changes = changes
    session.data.undo_branch_id = checkpoint
    automatic = sorted((b for b in session.data.branches.values() if b.automatic), key=lambda b: b.created_at)
    protected = {session.data.active_branch_id, checkpoint}
    remaining = len(automatic)
    for branch in automatic:
        if remaining <= MAX_AUTOMATIC_BRANCHES:
            break
        if branch.id not in protected:
            del session.data.branches[branch.id]
            remaining -= 1
    session.data.collect_history()
    session._changed()


def undo_turn(session) -> None:
    checkpoint = session.data.undo_branch_id
    if checkpoint is None or checkpoint not in session.data.branches:
        raise EngineError("there is no AI turn to undo")
    _idle(session)
    _remember(session)
    _activate(session, session.data.branches[checkpoint])
    session.data.undo_branch_id = None
    session._changed()


@contextmanager
def manual_edit(session, name: str):
    """Record one user transaction using the same snapshots as creative directions."""
    pending = any(step.status in ("proposed", "approved", "running") for step in session.data.steps)
    existing_nodes = set(session.data.history_nodes)
    active = session.data.active_branch_id or uuid.uuid4().hex
    before = _snapshot(session, active, name, time.time())
    try:
        yield
    finally:
        after = _snapshot(session, active, name, before.created_at)
        if after != before:
            if pending:
                session.data.manual_undo.clear()
                session.data.manual_redo.clear()
            else:
                if session.data.active_branch_id is None:
                    session.data.active_branch_id = active
                    session.data.branches[active] = after.model_copy(update={"name": "Original"})
                session.data.manual_undo = [*session.data.manual_undo, before][-30:]
                session.data.manual_redo.clear()
            session.data.collect_history()
            session._changed()
        else:
            # Capturing is speculative until the edit changes the document. Do not
            # leave records behind when a rejected edit has no observable effect.
            for key in set(session.data.history_nodes) - existing_nodes:
                del session.data.history_nodes[key]


def manual_restore(session, *, redo: bool = False) -> None:
    _idle(session)
    source = session.data.manual_redo if redo else session.data.manual_undo
    target = session.data.manual_undo if redo else session.data.manual_redo
    if not source:
        raise EngineError("there is no manual change to redo" if redo else "there is no manual change to undo")
    saved = source[-1]
    if saved.id != session.data.active_branch_id:
        raise EngineError("this change belongs to a different creative direction")
    current = _snapshot(session, saved.id, saved.name, time.time())
    source.pop()
    target.append(current)
    del target[:-30]
    name = session.data.branches[saved.id].name
    session.data.branches[saved.id] = saved.model_copy(deep=True, update={"name": name})
    _activate(session, saved, clear_history=False)
    session.changes = [f"the user {'redid' if redo else 'undid'} {saved.name}; use the restored timeline"]
    session._changed()
