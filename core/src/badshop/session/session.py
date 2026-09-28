"""A session: artifacts, steps and chat, and the one place every tool call goes through (spec 5, 5.3).

The user, the in-app agent and CLI agents all propose a step here and run it here, so the timeline,
approvals, edits and replay work the same for every caller. Engine rules still hold: nothing here prints,
and every failure a caller can act on is an EngineError."""

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
