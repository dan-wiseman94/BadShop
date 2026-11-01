"""Independent timelines sharing a project's immutable artifact store.

Switching snapshots the outgoing direction first: a switch is an edit to one document, never a
request to discard it. Saving that document includes all snapshots and their referenced artifacts.
"""

import copy
import time
import uuid

from badshop.engine.errors import EngineError
from badshop.session.models import BranchSnapshot


def _snapshot(session, id: str, name: str, created_at: float) -> BranchSnapshot:
    return BranchSnapshot(id=id, name=name, created_at=created_at,
                          steps=copy.deepcopy(session.data.steps), messages=copy.deepcopy(session.data.messages),
                          transcript=copy.deepcopy(session.data.transcript),
                          artifact_ids=sorted(session.visible_artifact_ids()))


def _remember(session) -> None:
    active = session.data.active_branch_id
    if active is None:
        active = uuid.uuid4().hex
        session.data.branches[active] = _snapshot(session, active, "Original", time.time())
        session.data.active_branch_id = active
    else:
        old = session.data.branches[active]
        session.data.branches[active] = _snapshot(session, active, old.name, old.created_at)


def listing(session) -> dict:
    active = session.data.active_branch_id
    rows = []
    for branch in session.data.branches.values():
        steps = session.data.steps if branch.id == active else branch.steps
        preview = next((s.outputs[0] for s in reversed(steps) if s.status == "done" and s.outputs), None)
        rows.append({"id": branch.id, "name": branch.name, "created_at": branch.created_at,
                     "step_count": len(steps), "preview_id": preview})
    return {"active_id": active, "branches": rows}


def _idle(session) -> None:
    if any(step.status in ("proposed", "approved", "running") for step in session.data.steps):
        raise EngineError("finish or reject pending steps before changing directions")


def create(session, name: str, from_step: str | None = None) -> None:
    _idle(session)
    index = None
    if from_step is not None:
        target = session.step(from_step)
        if target.status != "done":
            raise EngineError("choose a finished step to branch from")
        index = session.data.steps.index(target)
    _remember(session)
    id = uuid.uuid4().hex
    branch = _snapshot(session, id, name, time.time())
    if index is not None:
        removed = {s.id for s in branch.steps[index + 1:]}
        branch.steps = branch.steps[:index + 1]
        branch.artifact_ids = [aid for aid in branch.artifact_ids
                               if session.artifacts.meta[aid].produced_by not in removed]
        kept = {s.id for s in branch.steps}
        # A conversation after the cut may describe images no longer in this direction. Start a fresh
        # transcript and retain only self-contained user inputs and messages about retained steps.
        last_kept_message = max((i for i, m in enumerate(branch.messages)
                                 if m.step_ids and set(m.step_ids) <= kept), default=-1)
        branch.messages = [m for m in branch.messages[:last_kept_message + 1]
                           if not m.step_ids or set(m.step_ids) <= kept]
        branch.transcript = []
    session.data.branches[id] = branch
    _activate(session, branch)


def _activate(session, branch: BranchSnapshot) -> None:
    session.data.active_branch_id = branch.id
    session.data.steps = copy.deepcopy(branch.steps)
    session.data.messages = copy.deepcopy(branch.messages)
    # CLI processes are retired by CoreApp, API conversations are rebuilt with the new timeline.
    session.data.transcript = copy.deepcopy(branch.transcript)
    session.changes = [f"the user switched to creative direction {branch.name!r}; use its current timeline"]
    session._changed()


def switch(session, id: str) -> None:
    _idle(session)
    if id not in session.data.branches:
        raise EngineError("no such creative direction")
    if id == session.data.active_branch_id:
        return
    _remember(session)
    _activate(session, session.data.branches[id])


def rename(session, id: str, name: str) -> dict:
    if id not in session.data.branches:
        raise EngineError("no such creative direction")
    session.data.branches[id].name = name
    session._changed()
    return listing(session)


def remove(session, id: str) -> dict:
    if id == session.data.active_branch_id:
        raise EngineError("switch to another direction before removing this one")
    if id not in session.data.branches:
        raise EngineError("no such creative direction")
    del session.data.branches[id]
    session._changed()
    return listing(session)
