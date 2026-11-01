"""A session: artifacts, steps and chat, and the one place every tool call goes through (spec 5, 5.3).

The user, the in-app agent and CLI agents all propose a step here and run it here, so the timeline,
approvals, edits and replay work the same for every caller. Engine rules still hold: nothing here prints,
and every failure a caller can act on is an EngineError."""

import copy
import json
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter, ValidationError

from badshop import files
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.engine.types import FileName
from badshop.session import netpolicy
from badshop.session.artifacts import ArtifactStore, describe, short
from badshop.session.execution import (CRASH_HINT, STOPPED, Executor, InProcessExecutor, OutputRecord,
                                       ToolCall, ToolOutcome, cache_key, json_safe)
from badshop.session.models import ArtifactMeta, Message, Part, SessionData, Source, Step, StepError
from badshop.tools import registry, runner

Emit = Callable[[str, dict], None]

RUNNABLE = ("proposed", "approved")  # a step waiting to run; anything else has run, failed or been rejected
_MARKS = {"done": "✓", "error": "✗"}  # summary() writes every other status as its name
_ROOT_SUFFIX = re.compile(r"_(work|result)$")  # the CLI's clean_stem: lincoln_work names lincoln
_FILE_NAME = TypeAdapter(FileName)
_EXPORT_TRIES = 100  # names export tries before giving up, when other programs keep taking them first


def _crashed(e: Exception) -> ToolOutcome:
    return ToolOutcome(False, error_message=f"the tool crashed ({type(e).__name__}: {e})",
                       error_hint=CRASH_HINT, crashed=True)


def _image_refs(step: Step) -> list[str]:
    """The artifact ids a step reads, in field order (paste: base, then piece). A tool this version
    doesn't have reads nothing here; running it is the executor's clean "unknown tool" error."""
    spec = registry.REGISTRY.get(step.tool)
    refs: list[str] = []
    for name, is_list in (registry.image_fields(spec.params) if spec else {}).items():
        value = step.params.get(name)
        if value is not None:
            refs.extend(value if is_list else [value])
    return refs


# Steps the approval gate or a tool still owns: edit, replay and delete refuse to touch them.
_BUSY = {"proposed": "is waiting for approval", "approved": "is about to run", "running": "is running"}


def _map_refs(tool: str, params: dict, fn: Callable[[str], str]) -> dict:
    """A copy of stored params with every image ref passed through fn (replay's remap, short ids)."""
    out = dict(params)
    for name, is_list in registry.image_fields(registry.get(tool).params).items():
        value = out.get(name)
        if value is not None:
            out[name] = [fn(v) for v in value] if is_list else fn(value)
    return out


def _made(steps: list[Step]) -> set[str]:
    """Every artifact these steps output, a stopped replay's previous_outputs included."""
    return {id for s in steps for id in s.outputs + s.previous_outputs}


def _advance(remap: dict[str, str], old: list[str], new: list[str]) -> None:
    """Replay's table after a step made `new` where it used to make `old`: a later reference to its old
    output i now means its new output i. The newest producer before a reader wins, so an id this step
    makes again (or no longer makes) stops pointing at whatever an earlier step made in its place."""
    for i, o in enumerate(old):
        n = new[i] if i < len(new) else o
        if n != o:
            remap[o] = n
        else:
            remap.pop(o, None)


def label_for(record: OutputRecord, stem: str, tool: str) -> str:
    """An output's artifact label, from its name hint: `final:{stem}_deepfried` -> lincoln_deepfried,
    `fetch/lincoln_1.jpg` -> lincoln_1, `{stem}_work.png` -> lincoln_work. The generic `result.png`
    becomes lincoln_paste, or just paste when the step has no image input."""
    hint = record.name_hint
    if hint.startswith("final:"):  # a finished file's name has no extension: "my.meme" stays whole
        name = hint.removeprefix("final:").replace("{stem}", stem)
    else:
        name = PurePosixPath(hint.replace("{stem}", stem)).stem
    if name == "result":
        name = f"{stem}_{tool}" if stem else tool
    return name.strip("_") or tool


def result_text(step: Step, artifacts: ArtifactStore, outcome: ToolOutcome | None = None) -> str:
    """What the caller reads back (the agent's tool result, the step drawer): one line per output,
    `key: a3f9c1d2 (label, WxH) caption`, then the tool's own lines; `error:` and `hint:` for a failed
    step. Keys, captions and lines come from the run's outcome; without one, outputs are numbered."""
    if step.error is not None:
        return f"error: {step.error.message}" + (f"\nhint: {step.error.hint}" if step.error.hint else "")
    records = outcome.outputs if outcome is not None else []
    lines = []
    for i, id in enumerate(step.outputs):
        key, caption = (records[i].key, records[i].caption) if i < len(records) else (str(i + 1), "")
        lines.append(f"{key}: {describe(artifacts.meta[id])}" + (f" {caption}" if caption else ""))
    if outcome is not None:
        lines += outcome.lines
    return "\n".join(lines) or "done"


class _SessionStore:
    """The Store for tools that write files (export): they run in the session's process, because the
    output folder is the session's. Outputs are collected exactly as the worker collects them."""

    def __init__(self, session: "Session"):
        self.session = session
        self.records: list[OutputRecord] = []

    def load(self, ref: str):
        artifacts = self.session.artifacts
        return artifacts.image(artifacts.resolve(ref))

    def put(self, output: Output, stem: str) -> str:
        self.records.append(OutputRecord(output.key, output.encode(), output.name_hint, output.caption))
        return f"out:{len(self.records) - 1}"

    def export(self, ref: str, name: str | None) -> str:
        return str(self.session.export(ref, name))


class Session:
    """One open session. Not thread-safe: the server runs one call at a time (spec 5.6)."""

    def __init__(self, data: SessionData, artifacts: ArtifactStore, *, executor: Executor | None = None,
                 emit: Emit | None = None, output_dir: Path | None = None,
                 on_change: Callable[[], None] | None = None):
        self.data, self.artifacts = data, artifacts
        # One dict: a snapshot or a project file of `data` always lists every artifact the store holds.
        self.data.artifacts = artifacts.meta
        self.executor: Executor = executor if executor is not None else InProcessExecutor()
        self.emit: Emit = emit or (lambda event, payload: None)
        self.output_dir = output_dir if output_dir is not None else files.default_output_dir()
        self.on_change = on_change or (lambda: None)
        self.changes: list[str] = []  # what the user did that the agent hasn't heard about yet

    @classmethod
    def new(cls, name: str = "Untitled", **kw) -> "Session":
        data = SessionData(id=uuid.uuid4().hex, name=name, created_at=time.time())
        return cls(data, ArtifactStore(), **kw)

    # ids, lookups, events

    def _next_id(self, prefix: str) -> str:
        """s1, s2... and m1, m2...: one past the highest number anything still names, so an id never
        comes back while an artifact or a message points at it (the last step can be deleted)."""
        names = [s.id for s in self.data.steps] + [m.id for m in self.data.messages]
        names += [sid for m in self.data.messages for sid in m.step_ids]
        names += [a.produced_by for a in self.artifacts.meta.values() if a.produced_by]
        numbers = [int(n[len(prefix):]) for n in names if n.startswith(prefix) and n[len(prefix):].isdigit()]
        return f"{prefix}{max(numbers, default=0) + 1}"

    def step(self, step_id: str) -> Step:
        for s in self.data.steps:
            if s.id == step_id:
                return s
        raise EngineError(f"no such step: {step_id}", hint="use a step id from the timeline, like s3")

    def _emit(self, event: str, step: Step, outputs: Sequence[str] = ()) -> None:
        metas = [self.artifacts.meta[i].model_dump(mode="json") for i in dict.fromkeys(outputs)]
        self.emit(event, {"step": step.model_dump(mode="json"), "artifacts": metas})

    def _changed(self) -> None:
        self.on_change()

    def _resolved(self, params) -> dict:
        """Validated params as JSON, each image ref (an id or a unique prefix) replaced by the full id."""
        dumped = params.model_dump(mode="json")
        for name, is_list in registry.image_fields(type(params)).items():
            value = dumped.get(name)
            if value is not None:
                resolve = self.artifacts.resolve
                dumped[name] = [resolve(v) for v in value] if is_list else resolve(value)
        return dumped

    def _stem(self, step: Step) -> str:
        """What a step's outputs are named after: its first image input, traced back through the steps
        that made it to the picture it started from, so edits on lincoln give lincoln_text and then
        lincoln_deepfried, not lincoln_text_deepfried."""
        makers = {s.id: s for s in self.data.steps}
        refs, label, seen = _image_refs(step), "", set()
        while refs and refs[0] in self.artifacts and refs[0] not in seen:
            seen.add(refs[0])
            meta = self.artifacts.meta[refs[0]]
            label = meta.label
            maker = makers.get(meta.produced_by) if meta.produced_by else None
            refs = _image_refs(maker) if maker is not None else []
        return _ROOT_SUFFIX.sub("", label)

    # user input

    def import_image(self, data: bytes, label: str, source: Source | None = None) -> ArtifactMeta:
        """A dropped, pasted or opened picture: stored as a working copy (returned) plus the original.
        The agent hears about it in its next system note even when no message carries it (spec 5.3);
        the same picture added twice before then is one line."""
        working, _original = self.artifacts.import_image(data, label, source)
        if self.data.active_branch_id:
            branch = self.data.branches[self.data.active_branch_id]
            branch.artifact_ids = list(dict.fromkeys([*branch.artifact_ids, working.id, _original.id]))
        note = f"the user added image {self._named(working.id)}"
        if note not in self.changes:
            self.changes.append(note)
        self._changed()
        return working

    def add_message(self, role: str, parts: list[Part], step_ids: Sequence[str] = ()) -> Message:
        content = []
        for part in parts:
            if part.type == "image":
                if not part.artifact_id:
                    raise EngineError("an image part needs an artifact id")
                part = part.model_copy(update={"artifact_id": self.artifacts.resolve(part.artifact_id)})
            content.append(part)
        for sid in step_ids:
            self.step(sid)  # an unknown step id is this clean error
        message = Message(id=self._next_id("m"), role=role, content=content, step_ids=list(step_ids))
        self.data.messages.append(message)
        self._changed()
        return message

    # the step lifecycle: propose -> run (done | error) or reject

    def propose(self, tool: str, raw: dict, actor: str, reason: str | None = None) -> Step:
        """Validate a call for `actor` and add it as a proposed step. Image refs must name artifacts of
        this session (never paths, whoever asks); they are stored as full ids."""
        params = self._resolved(runner.validate(tool, raw, actor))
        step = Step(id=self._next_id("s"), index=len(self.data.steps) + 1, tool=tool, params=params,
                    actor=actor, status="proposed", reason=reason)
        self.data.steps.append(step)
        self._emit("step.proposed", step)
        self._changed()
        return step

    def run(self, step_id: str, raw: dict | None = None, *, cancel: threading.Event | None = None) -> Step:
        """Run a proposed step, with the user's edited params when given (validated as the user's).
        `cancel` is the caller's stop signal for this one run (the agent's Stop): it goes to the executor
        with the call, and a stopped run is a failed step with the executor's "stopped by the user"."""
        step = self.step(step_id)
        if step.status not in RUNNABLE:
            raise EngineError(f"step {step.id} is {step.status}, so it can't run",
                              hint="only a proposed step runs; edit a finished step and replay it instead")
        if raw is not None:
            params = self._resolved(runner.validate(step.tool, raw, "user"))
            if params != step.params:
                step.params, step.edited = params, True
        self._execute(step, cancel)
        if step.actor == "user":
            self.changes.append(self._change_note(step))
        return step

    def run_tool(self, tool: str, raw: dict, actor: str, reason: str | None = None) -> Step:
        return self.run(self.propose(tool, raw, actor, reason).id)

    def reject(self, step_id: str, note: str | None = None) -> Step:
        step = self.step(step_id)
        if step.status not in RUNNABLE:
            raise EngineError(f"step {step.id} is {step.status}, so it can't be rejected",
                              hint="only a step waiting for approval can be rejected")
        step.status, step.finished_at = "rejected", time.time()
        step.result_text = "rejected by user" + (f": {note}" if note else "")
        self._emit("step.finished", step)
        self._changed()
        return step

    def _execute(self, step: Step, cancel: threading.Event | None = None) -> Step:
        """Run a step's tool on its stored params and record the outcome. Never raises for a tool's
        failure: an EngineError, a crash, a killed worker or a stop (`cancel`, set by the caller) is a
        failed step with a clean error."""
        stem = self._stem(step)
        step.status, step.started_at, step.finished_at = "running", time.time(), None
        step.outputs, step.result_text, step.data, step.error = [], "", None, None
        step.cache_key = cache_key(step.tool, step.params)
        self._emit("step.started", step)  # no on_change here: an autosave never holds a running step
        try:
            if registry.get(step.tool).writes_files:
                outcome = self._run_here(step, stem, cancel)
            else:
                inputs = {id: self.artifacts.data(self.artifacts.resolve(id)) for id in _image_refs(step)}
                trusted = netpolicy.typed_urls(step.tool, step.params, step.actor)  # a user's own link
                call = ToolCall(step.tool, step.params, inputs, stem, trusted_urls=trusted,
                                guard_network=True)
                outcome = self.executor.run(call, cancel=cancel)  # the caller's stop goes with its call
            outputs = self._store_outputs(step, outcome, stem) if outcome.ok else []
        except EngineError as e:
            outcome, outputs = ToolOutcome(False, error_message=e.message, error_hint=e.hint), []
        except Exception as e:  # a bug, in the session or a tool: one failed step, the session goes on
            outcome, outputs = _crashed(e), []
        step.finished_at = time.time()
        if outcome.ok:
            step.status, step.outputs = "done", outputs
            step.data = {k: v for k, v in outcome.data.items() if k != "sources"} or None
        else:
            step.status = "error"
            step.error = StepError(message=outcome.error_message or "the tool failed",
                                   hint=outcome.error_hint)
        step.result_text = result_text(step, self.artifacts, outcome)
        self._emit("step.finished" if outcome.ok else "step.failed", step, step.outputs)
        self._changed()
        return step

    def _run_here(self, step: Step, stem: str, cancel: threading.Event | None) -> ToolOutcome:
        if cancel is not None and cancel.is_set():  # stopped before it began, as an executor answers
            return ToolOutcome(False, error_message=STOPPED)
        store = _SessionStore(self)
        params = registry.get(step.tool).params.model_validate(step.params)
        try:
            run = runner.execute(step.tool, params, store, stem=stem)
        except EngineError as e:
            return ToolOutcome(False, error_message=e.message, error_hint=e.hint)
        return ToolOutcome(True, store.records, list(run.result.lines), json_safe(run.result.data))

    def _store_outputs(self, step: Step, outcome: ToolOutcome, stem: str) -> list[str]:
        """Outputs become artifacts. A picture from outside (its `sources` entry is a dict) enters as a
        <=1000 px working copy with its original kept beside it (spec 5.3); the rest are stored as they
        are. Identical bytes are one artifact, which keeps the first step that made it."""
        sources = outcome.data.get("sources") or []
        ids = []
        for i, record in enumerate(outcome.outputs):
            label = label_for(record, stem, step.tool)
            source = sources[i] if i < len(sources) else None
            if isinstance(source, dict):  # working copy and original both record this step
                where = Source.model_validate(source)
                meta, _original = self.artifacts.import_image(record.data, label, where, produced_by=step.id)
            else:
                meta = self.artifacts.add(record.data, label, produced_by=step.id)
            ids.append(meta.id)
        return ids

    def _change_note(self, step: Step) -> str:
        """One line for the agent's next system note about a step the user ran."""
        spec = registry.get(step.tool)
        shown = spec.params.model_validate(step.params).model_dump(mode="json", exclude_defaults=True)
        for name, is_list in registry.image_fields(spec.params).items():
            if shown.get(name) is not None:
                shown[name] = [short(v) for v in shown[name]] if is_list else short(shown[name])
        call = f"{step.tool} {json.dumps(shown, ensure_ascii=False)}"
        if step.error is not None:
            return f"the user ran step {step.index}: {call}, which failed: {step.error.message}"
        made = ", ".join(self._named(i) for i in step.outputs) or "no images"
        return f"the user ran step {step.index}: {call} → {made}"

    # files and summaries

    def export(self, artifact_id: str, name: str | None = None) -> Path:
        """Write an artifact's bytes, unchanged, into the output folder as `name` (or its label) plus
        its format's extension, never overwriting: lincoln.png, lincoln_2.png..."""
        meta = self.artifacts.meta[self.artifacts.resolve(artifact_id)]
        if name is not None:
            try:
                name = _FILE_NAME.validate_python(name)
            except ValidationError as e:
                raise EngineError(f"bad file name {name!r}", hint=runner.explain(e)) from None
        stem, data = name or meta.label, self.artifacts.data(meta.id)
        try:
            for _ in range(_EXPORT_TRIES):
                path = files.final_path(self.output_dir, stem, meta.ext)
                try:
                    with open(path, "xb") as f:  # "x": a file that appeared since final_path looked is kept
                        f.write(data)
                    return path
                except FileExistsError:
                    # Another program took the name since final_path looked: the next try gets the next
                    # name. Not so for a broken link: final_path doesn't see it (it doesn't "exist"), so it
                    # would hand back this name forever, and "x" never replaces it.
                    if path.is_symlink() and not path.exists():
                        raise EngineError(f"can't write {path.name}: a broken link with that name is in "
                                          f"{self.output_dir}",
                                          hint="remove it, or export under another name") from None
        except OSError as e:
            raise EngineError(f"can't write into {self.output_dir} ({e})",
                              hint="check the output folder exists and is writable") from None
        raise EngineError(f"no free file name for {stem}{meta.ext} in {self.output_dir}",
                          hint="another program keeps taking those names; try again, or use another name")

    def _named(self, artifact_id: str) -> str:
        meta = self.artifacts.meta.get(artifact_id)
        return f"{short(artifact_id)} ({meta.label})" if meta else short(artifact_id)

    def last_output(self) -> str | None:
        """The newest finished picture: the last output of the latest done step (tools put the one to
        look at last: fetch's contact sheet, prep's grid)."""
        for step in reversed(self.data.steps):
            if step.status == "done" and step.outputs:
                return step.outputs[-1]
        return None

    def summary(self) -> str:
        """One line per step: `3. cutout by agent:fake ✓ → a3f9c1d2 (trump_cutout)`."""
        lines = []
        for step in self.data.steps:
            line = f"{step.index}. {step.tool} by {step.actor} {_MARKS.get(step.status, step.status)}"
            if step.edited:
                line += " (edited)"
            if step.outputs:
                line += " → " + ", ".join(self._named(i) for i in step.outputs)
            if step.error is not None:
                line += f": {step.error.message}"
            lines.append(line)
        return "\n".join(lines)

    def take_changes(self) -> list[str]:
        changes, self.changes = self.changes, []
        return changes

    # edit, replay, delete (spec 5.3, 7)

    def _position(self, step_id: str) -> int:
        step = self.step(step_id)  # an unknown id is step()'s clean EngineError
        return next(i for i, s in enumerate(self.data.steps) if s is step)

    @staticmethod
    def _refuse_busy(steps: list[Step]) -> None:
        for s in steps:
            if s.status in _BUSY:
                hint = ("approve or reject it first (the approval prompt can change its parameters)"
                        if s.status == "proposed" else "wait for it to finish, or press Stop")
                raise EngineError(f"step {s.index} ({s.tool}) {_BUSY[s.status]}", hint=hint)

    def _refuse_later(self, step: Step, pos: int, params: dict) -> None:
        """The timeline runs top to bottom: a step reads imports and what earlier steps made, never a
        picture that first came from itself or a later step. An artifact counts by its first producer,
        so an import that a step happens to make again (prep of a working copy gives the same bytes)
        is still the user's import, and a step may read it."""
        mine = {s.id for s in self.data.steps[pos:]}
        earlier = _made(self.data.steps[:pos])
        for id in _image_refs(step.model_copy(update={"params": params})):
            meta = self.artifacts.meta.get(id)
            if id in earlier or meta is None or meta.produced_by not in mine:
                continue
            maker = self.step(meta.produced_by)
            why = "it is this step's own output" if maker is step else f"step {maker.index} makes it later"
            raise EngineError(f"step {step.index} can't use {short(id)}: {why}",
                              hint="use an imported image or one an earlier step made")

    def _call(self, step: Step) -> str:
        """A step's call as a change note shows it: the params that differ from the defaults, short ids."""
        shown = registry.get(step.tool).params.model_validate(step.params).model_dump(mode="json",
                                                                                     exclude_defaults=True)
        return f"{step.tool} {json.dumps(_map_refs(step.tool, shown, short), ensure_ascii=False)}"

    def edit(self, step_id: str, raw: dict) -> list[Step]:
        """Give a finished (or failed, stale or rejected) step new params, as the user. It and every later
        step that was not rejected become `stale`; nothing runs until replay_from. Stale steps keep their
        old outputs and cache_key, which is how the replay finds results it can reuse. Params equal to the
        stored ones still mark the steps stale, but are not an edit: no `edited` flag, no change note."""
        pos = self._position(step_id)
        step = self.data.steps[pos]
        self._refuse_busy(self.data.steps[pos:])
        params = self._resolved(runner.validate(step.tool, raw, "user"))
        self._refuse_later(step, pos, params)
        changed = params != step.params
        if changed:
            step.params, step.edited = params, True
        stale = [step] + [s for s in self.data.steps[pos + 1:] if s.status != "rejected"]
        for s in stale:
            s.status = "stale"
        if changed:
            self.changes.append(f"the user edited step {step.index}: {self._call(step)}")
        self.emit("step.stale", {"step_ids": [s.id for s in stale]})
        self._changed()
        return stale

    def _executions(self) -> dict[str, Step]:
        """The successful runs the steps remember, by cache_key: done steps, and stale steps whose last
        run worked. Copies, so a replay that overwrites a step still finds what that step had."""
        return {s.cache_key: s.model_copy(deep=True) for s in self.data.steps
                if s.cache_key and s.error is None and s.status in ("done", "stale")}

    def _reuse(self, step: Step, hit: Step, key: str) -> None:
        """Take a remembered run's results instead of running: no step.started, only step.finished."""
        step.outputs, step.result_text = list(hit.outputs), hit.result_text
        step.data = copy.deepcopy(hit.data)
        step.status, step.error, step.cache_key = "done", None, key
        step.started_at = step.finished_at = time.time()
        self._emit("step.finished", step, step.outputs)

    def replay_from(self, step_id: str, *, use_cache: bool = True) -> list[Step]:
        """Re-execute a step and every later step that was not rejected, in order (spec 5.3).

        A reference to an old output of a re-executed step becomes the new output in the same position.
        A step whose rewritten params give the cache_key of an earlier successful run, all of whose outputs
        are still in the store, takes that run's results without running (use_cache=False runs every
        step). Stops at the first failure: that step is `error`, the steps after it stay `stale`, and
        their references already follow what the steps before the failure made. Returns the steps it
        processed, run or reused, the failed one last."""
        pos = self._position(step_id)
        behind = next((s for s in self.data.steps[:pos] if s.status == "stale" or s.previous_outputs), None)
        if behind is not None:  # these steps would run on inputs that are about to change
            raise EngineError(f"step {behind.index} ({behind.tool}) comes first and is not up to date",
                              hint=f"replay from step {behind.index} (if it failed, edit it first)")
        todo = [s for s in self.data.steps[pos:] if s.status != "rejected"]
        self._refuse_busy(todo)
        cache = self._executions() if use_cache else {}
        fresh = [s for s in todo if s.status != "stale"]
        for s in fresh:
            s.status = "stale"
        if fresh:
            self.emit("step.stale", {"step_ids": [s.id for s in fresh]})
        remap: dict[str, str] = {}
        processed: list[Step] = []
        failed: Step | None = None
        for step in todo:
            if remap:
                step.params = _map_refs(step.tool, step.params, lambda id: remap.get(id, id))
            old = list(step.outputs or step.previous_outputs)
            key = cache_key(step.tool, step.params)
            hit = cache.get(key)
            if hit is not None and all(id in self.artifacts for id in hit.outputs):
                self._reuse(step, hit, key)
            else:
                self._execute(step)  # never raises for the tool's failure; writes no change note
            processed.append(step)
            if step.status != "done":
                step.previous_outputs, failed = old, step
                break
            step.previous_outputs = []
            if use_cache:
                cache[key] = step.model_copy(deep=True)
            _advance(remap, old, step.outputs)
        if failed is not None:
            # The next replay starts at the failed step with an empty table, so the steps after it take
            # what ran before it now. They keep their last run (outputs, cache_key: still a true cache
            # entry) and stay stale. The failed step and each of them still stand for what they made
            # last time, so a reference to that stays put.
            _advance(remap, failed.previous_outputs, failed.previous_outputs)
            for rest in todo[len(processed):]:
                if remap:
                    rest.params = _map_refs(rest.tool, rest.params, lambda id: remap.get(id, id))
                made = rest.outputs or rest.previous_outputs
                _advance(remap, made, made)
            self.changes.append(f"the user replayed from step {todo[0].index}: step {failed.index} "
                                f"({failed.tool}) failed: {failed.error.message}; later steps are stale")
        elif processed:
            last = processed[-1]
            made = ", ".join(self._named(i) for i in last.outputs)
            self.changes.append(f"the user replayed steps {processed[0].index} to {last.index}"
                                + (f"; step {last.index} now gives {made}" if made else ""))
        self._changed()
        return processed

    def delete_last(self, step_id: str) -> None:
        """Delete the last step (spec 7: the last step only, in v1) and emit `step.deleted {"step_id"}`,
        an event spec 7's list gains here, so every client drops the step's card. Nothing else is
        rewritten: its artifacts stay in the store (a message, another step or an export may still show
        them), a message that lists it keeps listing it, and an artifact it made first keeps it as
        produced_by. Those records are what stop Task 7's _next_id from giving its id to a new step, and
        what lets referenced_ids keep the pictures a message's deleted step made."""
        step = self.step(step_id)
        last = self.data.steps[-1]
        if step is not last:
            raise EngineError(f"only the last step can be deleted, and step {step.index} is not the last",
                              hint=f"delete step {last.index} first, then work backwards")
        self._refuse_busy([step])
        self.data.steps.pop()
        self.changes.append(f"the user deleted step {step.index} ({step.tool})")
        self.emit("step.deleted", {"step_id": step.id})
        self._changed()

    @staticmethod
    def _mentioned(value: object, shorts: set[str]) -> set[str]:
        """The short ids in `shorts` that appear in any string inside `value`, a JSON value such as the
        transcript (contents and tool-call arguments) or a list of message texts. A short id counts
        wherever it sits in a run of hex digits, so a full id or a longer prefix mentions it too. Walked
        with a list, not recursion, because a transcript read from a project file may nest deeply."""
        found: set[str] = set()
        todo = [value]
        while todo:
            item = todo.pop()
            if isinstance(item, str):
                for run in re.findall(r"[0-9a-f]{8,}", item):
                    found |= shorts.intersection(run[i:i + 8] for i in range(len(run) - 7))
            elif isinstance(item, dict):
                todo.extend(item.values())
            elif isinstance(item, list):
                todo.extend(item)
        return found

    def visible_artifact_ids(self) -> set[str]:
        """Images belonging to the active direction; other directions still share the byte store."""
        if self.data.active_branch_id is None:
            return set(self.artifacts.ids())
        branch = self.data.branches[self.data.active_branch_id]
        ids = set(branch.artifact_ids)
        for step in self.data.steps:
            ids.update(_image_refs(step), step.outputs, step.previous_outputs)
        for message in self.data.messages:
            ids.update(p.artifact_id for p in message.content if p.type == "image" and p.artifact_id)
        ids.update(self.artifacts.meta[aid].original_id for aid in list(ids)
                   if aid in self.artifacts.meta and self.artifacts.meta[aid].original_id)
        return ids & set(self.artifacts.ids())

    def referenced_ids(self) -> set[str]:
        """The artifacts the session still points at, which project save (Task 9) keeps: every image the
        user imported, used or not; every step's inputs and outputs (and a stopped replay's
        previous_outputs); the images in messages; what each step a message names made first (its
        produced_by), which for a deleted step is what is left of its outputs; every artifact whose short
        id appears in the transcript or in a message's text; and the originals of all of those that are
        imports. So a reopened session never loses a picture the user added or the chat or the model
        still points at (spec 2, criterion 4)."""
        meta = self.artifacts.meta
        # The user's imports are the working copies no step produced. They stay even before any step,
        # message or agent turn names them, so a save or autosave right after a drop keeps the picture.
        originals = {a.original_id for a in meta.values() if a.original_id}
        ids = {i for i, a in meta.items() if a.produced_by is None and i not in originals}
        for s in self.data.steps:
            ids.update(_image_refs(s), s.outputs, s.previous_outputs)
        named: set[str] = set()
        texts: list[str] = []
        for m in self.data.messages:
            named.update(m.step_ids)
            ids.update(p.artifact_id for p in m.content if p.type == "image" and p.artifact_id)
            texts.extend(p.text for p in m.content if p.text)
        ids.update(i for i, a in meta.items() if a.produced_by in named)
        by_short: dict[str, list[str]] = {}
        for i in meta:
            by_short.setdefault(short(i), []).append(i)
        for found in self._mentioned([self.data.transcript, texts], set(by_short)):
            ids.update(by_short[found])
        for branch in self.data.branches.values():
            ids.update(branch.artifact_ids)
        originals = [meta[i].original_id for i in ids if i in meta]
        ids.update(o for o in originals if o)
        return ids
