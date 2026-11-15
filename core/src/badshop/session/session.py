"""A session: artifacts, steps and chat, and the one place every tool call goes through (spec 5, 5.3).

The user, the in-app agent and CLI agents all propose a step here and run it here, so the timeline,
approvals, edits and replay work the same for every caller. Engine rules still hold: nothing here prints,
and every failure a caller can act on is an EngineError."""

import copy
import hashlib
import io
import json
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter, ValidationError
from PIL.PngImagePlugin import PngInfo

from badshop import atomic, files
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.engine.types import FileName
from badshop.session import netpolicy
from badshop.session.artifacts import ArtifactStore, describe, short
from badshop.session.execution import (CRASH_HINT, STOPPED, MAX_INPUT_BYTES, Executor, InProcessExecutor, OutputRecord,
                                       ToolCall, ToolOutcome, cache_key, json_safe)
from badshop.session.models import ArtifactMeta, Message, Part, SessionData, Source, Step, StepError
from badshop.session.invocation_policy import ExecutionBudget, OPERATION_ID
from badshop.tools import registry, runner

Emit = Callable[[str, dict], None]
BYPASS_TOOLS = frozenset({"filter", "deepfry", "save", "eyes", "sparkle", "flare", "watermark", "warp", "censor", "palette"})

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
    return registry.image_refs(spec.params, step.params) if spec else []


# Steps the approval gate or a tool still owns: edit, replay and delete refuse to touch them.
_BUSY = {"proposed": "is waiting for approval", "approved": "is about to run", "running": "is running"}


def _map_refs(tool: str, params: dict, fn: Callable[[str], str]) -> dict:
    """A copy of stored params with every image ref passed through fn (replay's remap, short ids)."""
    return registry.map_image_refs(registry.get(tool).params, params, fn)


def _made(steps: list[Step]) -> set[str]:
    """Every artifact these steps output, a stopped replay's previous_outputs included."""
    return {id for s in steps for id in s.outputs + s.previous_outputs}


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


def _output_keys(outcome: ToolOutcome) -> list[str]:
    """Acquired list members bind to source evidence and bytes, never search position."""
    sources = outcome.data.get('sources') or []
    keys = []
    for index, record in enumerate(outcome.outputs):
        source = sources[index] if index < len(sources) else None
        if isinstance(source, dict):
            evidence = json.dumps(source, sort_keys=True, ensure_ascii=True).encode('ascii')
            digest = hashlib.sha256(evidence + b'\0')
            digest.update(record.data)
            keys.append('source:' + digest.hexdigest())
        else:
            keys.append(record.key)
    return keys


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
                 on_change: Callable[[], None] | None = None, decoder=None):
        self.data, self.artifacts = data, artifacts
        self.incarnation = uuid.uuid4().hex  # reopening the same saved ID creates a new live owner
        if decoder is not None:
            self.artifacts.decoder = decoder
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
        for snapshot in [*self.data.manual_undo, *self.data.manual_redo]:
            names.extend((f's{snapshot.max_step_number}', f'm{snapshot.max_message_number}'))
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

    def _inputs(self, step: Step) -> dict[str, bytes]:
        ids = list(dict.fromkeys(self.artifacts.resolve(aid) for aid in _image_refs(step)))
        if sum(self.artifacts.size(aid) for aid in ids) > MAX_INPUT_BYTES:
            raise EngineError('this operation exceeds the 256 MiB encoded input budget',
                              hint='use fewer inputs or smaller working copies')
        return {aid: self.artifacts.data(aid) for aid in ids}

    def read_only_reason(self) -> str | None:
        unknown = sorted({step.tool for step in self.data.steps if step.tool not in registry.REGISTRY})
        return ('This project uses unavailable tools: ' + ', '.join(unknown)
                + '. Inspect or export its images, save a copy, or open it with a compatible version.') if unknown else None

    def _resolved(self, params) -> dict:
        """Validated params as JSON, each image ref (an id or a unique prefix) replaced by the full id."""
        return registry.map_image_refs(type(params), params.model_dump(mode="json"), self.artifacts.resolve)

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

    def _bind_inputs(self, step: Step) -> None:
        producers = {aid: (previous.invocation_id, port)
                     for previous in self.data.steps[:step.index - 1]
                     for port, aid in previous.output_ports.items()}
        step.input_bindings = {aid: producers[aid] for aid in _image_refs(step) if aid in producers}

    def _resolve_bindings(self, step: Step) -> None:
        producers = {previous.invocation_id: previous for previous in self.data.steps[:step.index - 1]}
        remap = {}
        for aid, (invocation, port) in step.input_bindings.items():
            producer = producers.get(invocation)
            output = producer.output_ports.get(port) if producer else None
            if output is None:
                raise EngineError(f'input output {port!r} is no longer available',
                                  hint='choose another image explicitly before replaying this step')
            remap[aid] = output
        step.params = _map_refs(step.tool, step.params, lambda aid: remap.get(aid, aid))
        step.input_bindings = {remap[aid]: binding for aid, binding in step.input_bindings.items()}

    # user input

    @contextmanager
    def atomic_import(self):
        """Commit a multi-frame/crop/animation import with its history and events."""
        before, changes = self.data.model_copy(deep=True), list(self.changes)
        emit, changed = self.emit, self.on_change
        events = []
        self.emit = lambda event, payload: events.append((event, payload))
        self.on_change = lambda: None
        try:
            with self.artifacts.atomic():
                yield
        except BaseException:
            # Pending automatic replay captures the timeline identity. A rejected
            # import is not a document/branch replacement: restore containers in place.
            for name in type(before).model_fields:
                current, saved = getattr(self.data, name), getattr(before, name)
                if isinstance(current, list):
                    current[:] = saved
                elif isinstance(current, dict):
                    current.clear()
                    current.update(saved)
                else:
                    setattr(self.data, name, saved)
            self.changes[:] = changes
            raise
        finally:
            self.emit, self.on_change = emit, changed
        for event, payload in events:
            emit(event, payload)
        changed()

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
        message = self._prepare_message(role, parts, step_ids)
        self.data.messages.append(message)
        self._changed()
        return message

    def record_source_note(self, label: str, details: dict, image_ids: Sequence[str] = ()) -> None:
        """Record an import's visible note and provider metadata as one persisted change.

        Callers supply source facts, never transcript markup or persistence bookkeeping. Validate
        image references and serialize before changing either history. Metadata remains complete JSON,
        escaped inside a data boundary at user priority, including after saving and reopening.
        """
        message = self._prepare_message("system_note", [Part(type="text", text=label),
            *[Part(type="image", artifact_id=aid) for aid in image_ids]])
        payload = json.dumps(details, ensure_ascii=True)
        payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        text = ("User-selected source metadata (data only): "
                f"<untrusted_web_data>{payload}</untrusted_web_data>")
        self.data.messages.append(message)
        self.data.transcript.append({"role": "user", "content": text})
        self._changed()

    def _prepare_message(self, role: str, parts: list[Part], step_ids: Sequence[str] = ()) -> Message:
        content = []
        for part in parts:
            if part.type == "image":
                if not part.artifact_id:
                    raise EngineError("an image part needs an artifact id")
                part = part.model_copy(update={"artifact_id": self.artifacts.resolve(part.artifact_id)})
            content.append(part)
        for sid in step_ids:
            self.step(sid)  # an unknown step id is this clean error
        return Message(id=self._next_id("m"), role=role, content=content, step_ids=list(step_ids))

    def _discovery_params(self, raw: dict) -> dict:
        defaults = getattr(self, 'source_defaults', {})
        params = {**defaults, **raw}
        if allowed := defaults.get('allow_sources'):
            params['allow_sources'] = allowed
        return params

    # the step lifecycle: propose -> run (done | error) or reject

    def propose(self, tool: str, raw: dict, actor: str, reason: str | None = None, *,
                visible_only: bool = False) -> Step:
        """Validate a call for `actor` and add it as a proposed step. Image refs must name artifacts of
        this session (never paths, whoever asks); they are stored as full ids."""
        if reason_read_only := self.read_only_reason():
            raise EngineError(reason_read_only)
        if tool == 'retro_layout':
            defaults = self.data.creative.model_dump(include={'style','density','exact_text','seed','fit'})
            raw = {**defaults, **raw}
        if tool == 'animate_sticker':
            raw = {'delay': self.data.creative.animation_delay, **raw}
        if tool == 'discover':
            raw = self._discovery_params(raw)
        checked = runner.validate(tool, raw, actor)
        params = self._resolved(checked)
        if visible_only:
            refs = registry.image_refs(type(checked), params)
            if refs and not self.visible_artifact_ids().issuperset(refs):
                raise EngineError("this tool input is outside the CLI direction")
        if not runner.is_trusted(actor):
            self.data.manual_undo.clear()
            self.data.manual_redo.clear()
        step = Step(id=self._next_id("s"), index=len(self.data.steps) + 1, tool=tool, params=params,
                    actor=actor, status="proposed", reason=reason, operation_id=OPERATION_ID.get())
        self._bind_inputs(step)
        if not runner.is_trusted(actor) and registry.get(tool).mutates:
            ancestry = set(_image_refs(step))
            for previous in reversed(self.data.steps):
                if ancestry.intersection(previous.outputs):
                    ancestry.update(_image_refs(previous))
            step.lock_review = any(previous.locked_fields and (
                ancestry.intersection(previous.outputs) or
                (previous.tool == tool and ancestry.intersection(_image_refs(previous)))
            ) for previous in self.data.steps)
            if step.lock_review:
                step.reason = "Review required: this operation may change a result with pinned settings. " + (reason or "")
        self.data.steps.append(step)
        self._emit("step.proposed", step)
        self._changed()
        return step

    def run(self, step_id: str, raw: dict | None = None, *, cancel: threading.Event | None = None,
            budget: ExecutionBudget | None = None, portable: bool = False) -> Step:
        """Run a proposed step, with the user's edited params when given (validated as the user's).
        `cancel` is the caller's stop signal for this one run (the agent's Stop): it goes to the executor
        with the call, and a stopped run is a failed step with the executor's "stopped by the user"."""
        step = self.step(step_id)
        if step.status not in RUNNABLE:
            raise EngineError(f"step {step.id} is {step.status}, so it can't run",
                              hint="only a proposed step runs; edit a finished step and replay it instead")
        if step.lock_review and not step.lock_approved and not runner.is_trusted(step.actor):
            raise EngineError("this operation requires review of pinned settings")
        if budget is not None and budget.exhausted:
            return self.reject(step_id, "this turn's tool budget is used up")
        if raw is not None:
            params = self.validate_step_params(step_id, raw)
            if params != step.params:
                step.params, step.edited = params, True
                self._bind_inputs(step)
        if budget is not None:
            budget.record_execution()
        self._execute(step, cancel, replay=portable, user_edited=raw is not None)
        if step.actor == "user":
            self.changes.append(self._change_note(step))
        return step

    def run_approved(self, step_id: str, raw: dict | None = None, *, cancel: threading.Event | None = None,
                     budget: ExecutionBudget | None = None) -> Step:
        """Settle a decided approval even if its edited parameters no longer resolve.

        The caller holds the document lock. Validation failures without an edit
        are programming errors and propagate; invalid edits leave no orphan waiter.
        """
        try:
            return self.run(step_id, raw, cancel=cancel, budget=budget)
        except EngineError as error:
            if raw is None:
                raise
            return self.reject(step_id, f"the edited parameters were refused: {error.message}")

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

    def _execute(self, step: Step, cancel: threading.Event | None = None, *,
                 replay: bool = False, user_edited: bool = False, local_only: bool = False) -> Step:
        """Run a step's tool on its stored params and record the outcome. Never raises for a tool's
        failure: an EngineError, a crash, a killed worker or a stop (`cancel`, set by the caller) is a
        failed step with a clean error."""
        stem = self._stem(step)
        step.status, step.started_at, step.finished_at = "running", time.time(), None
        step.outputs, step.result_text, step.data, step.error = [], "", None, None
        step.cache_key = cache_key(step.tool, {**step.params, "_bypass_step": step.id} if step.bypassed else step.params)
        try:
            self._changed()
            self._emit("step.started", step)  # recovery normalizes an interrupted running step on reopen
            if step.bypassed:
                if step.tool not in BYPASS_TOOLS:
                    raise EngineError("this tool cannot be bypassed")
                if self.artifacts.meta[step.params["image"]].frames > 1:
                    raise EngineError("bypass is only available for still images")
                source = self.artifacts.image(step.params["image"])
                buffer = io.BytesIO()
                metadata = PngInfo()
                metadata.add_text("badshop-bypass", step.id)
                source.save(buffer, "PNG", pnginfo=metadata)
                outcome = ToolOutcome(True, [OutputRecord("result", buffer.getvalue(), "result.png")])
            elif registry.get(step.tool).writes_files:
                outcome = self._run_here(step, stem, cancel)
            else:
                # An archive, recovery snapshot or history revision can supply any recorded actor.
                # A replay may reuse existing output, but cannot recreate a privileged input.
                actor = "replay" if replay else step.actor
                if replay:
                    runner.validate(step.tool, step.params, actor)
                inputs = self._inputs(step)
                trusted = netpolicy.typed_urls(step.tool, step.params, actor)
                call = ToolCall(step.tool, step.params, inputs, stem, trusted_urls=trusted,
                                guard_network=True, no_remote=local_only or getattr(self, 'no_remote', False),
                                catalogue_font=replay or (not user_edited and not runner.is_trusted(actor)))
                outcome = self.executor.run(call, cancel=cancel)  # the caller's stop goes with its call
            if outcome.ok and len(set(_output_keys(outcome))) != len(outcome.outputs):
                raise EngineError('tool returned duplicate output names')
            with self.artifacts.atomic():
                outputs = self._store_outputs(step, outcome, stem) if outcome.ok else []
        except EngineError as e:
            outcome, outputs = ToolOutcome(False, error_message=e.message, error_hint=e.hint), []
        except Exception as e:  # a bug, in the session or a tool: one failed step, the session goes on
            outcome, outputs = _crashed(e), []
        step.finished_at = time.time()
        step.data = {k: v for k, v in outcome.data.items() if k != "sources"} or None
        if outcome.ok:
            step.status, step.outputs = "done", outputs
            ports = dict(zip(_output_keys(outcome), outputs, strict=True))
            legacy = {f'legacy:{i}': key for i, key in enumerate(_output_keys(outcome))}
            if any(key.startswith('legacy:') for key in step.output_ports):
                for consumer in self.data.steps:
                    consumer.input_bindings = {aid: (invocation, legacy.get(port, port))
                        if invocation == step.invocation_id else (invocation, port)
                        for aid, (invocation, port) in consumer.input_bindings.items()}
            step.output_ports = ports
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
        are. Each invocation and output name owns its provenance; bytes remain shared."""
        sources = outcome.data.get("sources") or []
        ids = []
        keys = _output_keys(outcome)
        for i, record in enumerate(outcome.outputs):
            label = label_for(record, stem, step.tool)
            source = sources[i] if i < len(sources) else None
            if isinstance(source, dict):  # working copy and original both record this step
                where = Source.model_validate(source)
                meta, _original = self.artifacts.import_image(record.data, label, where, produced_by=step.id,
                                                             invocation_id=step.invocation_id, output_key=keys[i])
            else:
                meta = self.artifacts.add(record.data, label, produced_by=step.id, new_use=True,
                                          invocation_id=step.invocation_id, output_key=keys[i],
                                          input_ids=tuple(_image_refs(step)))
            ids.append(meta.id)
        return ids

    def _change_note(self, step: Step) -> str:
        """One line for the agent's next system note about a step the user ran."""
        spec = registry.get(step.tool)
        shown = spec.params.model_validate(step.params).model_dump(mode="json", exclude_defaults=True)
        shown = registry.map_image_refs(spec.params, shown, short)
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
                    atomic.write_new_bytes(path, data)
                    return path
                except FileExistsError:
                    # Another program took the name since final_path looked: the next try gets the next
                    # name. Not so for a broken link: final_path doesn't see it (it doesn't "exist"), so it
                    # would hand back this name forever, and publication never replaces it.
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

    def summary(self, *, limit: int | None = None) -> str:
        """One line per step: `3. cutout by agent:fake ✓ → a3f9c1d2 (trump_cutout)`."""
        lines = []
        for step in self.data.steps[-limit:] if limit else self.data.steps:
            line = f"{step.index}. {step.tool} by {step.actor} {_MARKS.get(step.status, step.status)}"
            if step.edited:
                line += " (edited)"
            if step.bypassed:
                line += " (bypassed)"
            if step.locked_fields:
                line += " locked settings: " + json.dumps({key: step.params.get(key) for key in step.locked_fields})
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

    def validate_step_params(self, step_id: str, raw: dict) -> dict:
        """Check a user's edit without changing the step or consuming a pending approval."""
        pos = self._position(step_id)
        step = self.data.steps[pos]
        params = self._resolved(runner.validate(step.tool, raw, "user"))
        self._refuse_later(step, pos, params)
        return params

    @staticmethod
    def _local_refusal(tool: str) -> tuple[str, str] | None:
        spec = registry.get(tool)
        if spec.writes_files:
            return "file_write", "writes files"
        if spec.network:
            return "network_step", "requires network access"
        return None

    def _final_preview_refusal(self, step_id: str) -> tuple[str, str] | None:
        if len(self.data.steps[self._position(step_id):]) > 60:
            return "operation_limit", "Final preview is limited to 60 operations."
        if self.local_replay_blocker(step_id) is not None:
            return "network_step", "Final preview requires local steps without file writes."
        return None

    def plan_preview(self, raw: dict, scope: str, *, step_id: str | None, tool: str | None) -> dict:
        """Describe the local preview and Apply paths without executing a tool."""
        plan = {"eligible": False, "scope": "step", "later_steps": 0, "can_apply_local": False}

        def refuse(reason, message):
            return {**plan, "reason": reason, "message": message}

        try:
            self._refuse_busy(self.data.steps)
        except EngineError as error:
            return refuse("busy", error.message)
        if step_id is not None:
            try:
                step = self.step(step_id)
            except EngineError as error:
                return refuse("missing_target", error.message)
            tool = step.tool
            if step.bypassed:
                return refuse("bypassed", "Enable this effect before previewing its settings.")
        try:
            refusal = self._local_refusal(tool)
            if refusal:
                reason, detail = refusal
                return refuse(reason, f"This tool {detail}.")
            if step_id is not None:
                self.validate_step_params(step_id, raw)
            else:
                self._resolved(runner.validate(tool, raw, "user"))
        except EngineError as error:
            return refuse("invalid_params", error.message)
        plan["eligible"] = True
        if step_id is None:
            return plan
        plan["later_steps"] = sum(item.status != "rejected" for item in self.data.steps[self._position(step_id) + 1:])
        try:
            blocker = self.local_replay_blocker(step_id)
        except EngineError as error:
            return refuse("earlier_stale", error.message)
        if blocker:
            step, reason, detail = blocker
            message = f"Step {step.index} ({step.tool}) {detail}."
            return {**refuse(reason, message), "blocker": {
                "step_id": step.id, "invocation_id": step.invocation_id, "message": message,
            }}
        plan["can_apply_local"] = True
        if scope == "final":
            refusal = self._final_preview_refusal(step_id)
            if refusal:
                return refuse(*refusal)
            plan["scope"] = "final"
        return plan

    def preview_edit(self, step_id: str, raw: dict, *, final_result: bool = False) -> list[OutputRecord]:
        """Render one local step without publishing artifacts, history or change events."""
        step = self.step(step_id)
        self._refuse_busy(self.data.steps)
        if step.bypassed:
            raise EngineError("enable this effect before previewing its settings")
        params = self.validate_step_params(step_id, raw)
        if final_result:
            if refusal := self._final_preview_refusal(step_id):
                raise EngineError(refusal[1].lower().rstrip("."), hint="preview this step alone instead")
            # Own metadata and dictionaries; immutable bytes can safely be shared.
            store = self.artifacts.fork()
            try:
                shadow = Session(self.data.model_copy(deep=True), store, executor=self.executor,
                                 output_dir=self.output_dir, decoder=self.artifacts.decoder)
                shadow.no_remote = True
                shadow.edit(step_id, params)
                completed = shadow.replay_from(step_id)
                failed = next((item for item in completed if item.status == "error"), None)
                if failed:
                    raise EngineError(failed.error.message, hint=failed.error.hint)
                last = next((item for item in reversed(completed) if item.outputs), None)
                return [OutputRecord("preview", store.data(aid), "preview.png", "")
                        for aid in (last.outputs if last else [])]
            finally:
                store.close()
        # This form also carries stored step parameters, including from shared projects.
        return self.preview_tool(step.tool, params, portable=True)

    def local_preview_call(self, tool: str, params: dict, *, portable: bool = False) -> ToolCall:
        """Capture immutable inputs for a previously validated preview."""
        if self._local_refusal(tool):
            raise EngineError("preview requires a local image tool")
        draft = Step(id="preview", index=0, tool=tool, params=params, actor="user", status="proposed")
        return ToolCall(tool, params, self._inputs(draft), self._stem(draft),
                        guard_network=True, no_remote=True, catalogue_font=portable)

    def preview_tool(self, tool: str, raw: dict, *, portable: bool = False) -> list[OutputRecord]:
        """Use the existing executor for a disposable preview; never publish project state."""
        self._refuse_busy(self.data.steps)
        params = self._resolved(runner.validate(tool, raw, "replay" if portable else "user"))
        outcome = self.executor.run(self.local_preview_call(tool, params, portable=portable))
        if not outcome.ok:
            raise EngineError(outcome.error_message or "preview failed", hint=outcome.error_hint)
        return outcome.outputs

    def edit(self, step_id: str, raw: dict) -> list[Step]:
        """Give a finished (or failed, stale or rejected) step new params, as the user. It and every later
        step that was not rejected become `stale`; nothing runs until replay_from. Stale steps keep their
        old outputs and cache_key, which is how the replay finds results it can reuse. Params equal to the
        stored ones still mark the steps stale, but are not an edit: no `edited` flag, no change note."""
        pos = self._position(step_id)
        step = self.data.steps[pos]
        self._refuse_busy(self.data.steps[pos:])
        params = self.validate_step_params(step_id, raw)
        changed = params != step.params
        if changed:
            saved_bindings = step.input_bindings
            step.params, step.edited = params, True
            self._bind_inputs(step)
            # A text-only edit must still follow the previously selected output
            # port, even when replay removed that port's current artifact.
            step.input_bindings.update({aid: saved_bindings[aid] for aid in _image_refs(step)
                                        if aid in saved_bindings})
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
                if s.cache_key and s.error is None and s.status in ("done", "stale")
                and not registry.get(s.tool).writes_files}

    def _reuse(self, step: Step, hit: Step, key: str) -> None:
        """Take a remembered run's results instead of running: no step.started, only step.finished."""
        step.outputs, step.result_text = list(hit.outputs), hit.result_text
        step.output_ports = dict(hit.output_ports)
        if step.invocation_id != hit.invocation_id:
            step.output_ports = {port: self.artifacts.clone_use(aid, produced_by=step.id,
                invocation_id=step.invocation_id, output_key=port).id for port, aid in hit.output_ports.items()}
            step.outputs = list(step.output_ports.values())
            lines = hit.result_text.split('\n')
            for index, (old, new) in enumerate(zip(hit.outputs, step.outputs, strict=True)):
                if index < len(lines):
                    lines[index] = lines[index].replace(describe(self.artifacts.meta[old]),
                                                        describe(self.artifacts.meta[new]), 1)
            step.result_text = '\n'.join(lines)
        step.data = copy.deepcopy(hit.data)
        step.status, step.error, step.cache_key = "done", None, key
        step.started_at = step.finished_at = time.time()
        self._emit("step.finished", step, step.outputs)

    def _replay_suffix(self, step_id: str, *, include_target: bool = False) -> list[Step]:
        pos = self._position(step_id)
        behind = next((s for s in self.data.steps[:pos] if s.status == "stale" or s.previous_outputs), None)
        if behind is not None:
            raise EngineError(f"step {behind.index} ({behind.tool}) comes first and is not up to date",
                              hint=f"replay from step {behind.index} (if it failed, edit it first)")
        todo = [s for s in self.data.steps[pos:]
                if s.status != "rejected" or (include_target and s.id == step_id)]
        self._refuse_busy(todo)
        return todo

    def local_replay_blocker(self, step_id: str) -> tuple[Step, str, str] | None:
        # Editing revives the target even if it was previously rejected.
        for step in self._replay_suffix(step_id, include_target=True):
            if refusal := self._local_refusal(step.tool):
                return step, *refusal
        return None

    def replay_from(self, step_id: str, *, use_cache: bool = True, local_only: bool = False) -> list[Step]:
        """Re-execute a step and every later step that was not rejected, in order (spec 5.3).

        Bound inputs follow the producing invocation's named output across re-execution.
        A step whose rewritten params give the cache_key of an earlier successful run, all of whose outputs
        are still in the store, takes that run's results without running (use_cache=False runs every
        step). Stops at the first failure: that step is `error`, the steps after it stay `stale`, and
        their references already follow what the steps before the failure made. Returns the steps it
        processed, run or reused, the failed one last."""
        todo = self._replay_suffix(step_id)
        cache = self._executions() if use_cache else {}
        fresh = [s for s in todo if s.status != "stale"]
        for s in fresh:
            s.status = "stale"
        if fresh:
            self.emit("step.stale", {"step_ids": [s.id for s in fresh]})
        processed: list[Step] = []
        failed: Step | None = None
        for step in todo:
            old = list(step.outputs or step.previous_outputs)
            try:
                self._resolve_bindings(step)
                key = cache_key(step.tool, {**step.params, "_bypass_step": step.id} if step.bypassed else step.params)
                hit = cache.get(key)
                if hit is not None and all(id in self.artifacts for id in hit.outputs):
                    self._reuse(step, hit, key)
                else:
                    self._execute(step, replay=True, local_only=local_only)
            except EngineError as error:
                step.status, step.error = 'error', StepError(message=error.message, hint=error.hint)
                step.finished_at = time.time()
                step.result_text = result_text(step, self.artifacts)
                self._emit('step.failed', step)
            processed.append(step)
            if step.status != "done":
                step.previous_outputs, failed = old, step
                break
            step.previous_outputs = []
            if use_cache and not registry.get(step.tool).writes_files:
                cache[key] = step.model_copy(deep=True)
        if failed is not None:
            # The next replay starts at the failed step with an empty table, so the steps after it take
            # what ran before it now. They keep their last run (outputs, cache_key: still a true cache
            # entry) and stay stale. The failed step and each of them still stand for what they made
            # last time, so a reference to that stays put.
            for rest in todo[len(processed):]:
                try:
                    self._resolve_bindings(rest)
                except EngineError:
                    pass  # Keep the unresolved binding; retry cannot silently use historical bytes.
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
        ids.update(self.data.creative.source_roles.values())
        for step in self.data.steps:
            ids.update(_image_refs(step), step.outputs, step.previous_outputs)
        for message in self.data.messages:
            ids.update(p.artifact_id for p in message.content if p.type == "image" and p.artifact_id)
        ids.update(self.artifacts.meta[aid].original_id for aid in list(ids)
                   if aid in self.artifacts.meta and self.artifacts.meta[aid].original_id)
        return ids & set(self.artifacts.ids())

    def referenced_ids(self) -> set[str]:
        return referenced_ids(self.data, self.artifacts.meta)


def referenced_ids(data: SessionData, meta: dict[str, ArtifactMeta]) -> set[str]:
    """The artifacts the session still points at, which project save (Task 9) keeps: every image the
    user imported, used or not; every step's inputs and outputs (and a stopped replay's
    previous_outputs); the images in messages; what each step a message names made first (its
    produced_by), which for a deleted step is what is left of its outputs; every artifact whose short
    id appears in the transcript or in a message's text; and the originals of all of those that are
    imports. So a reopened session never loses a picture the user added or the chat or the model
    still points at (spec 2, criterion 4)."""
    # The user's imports are the working copies no step produced. They stay even before any step,
    # message or agent turn names them, so a save or autosave right after a drop keeps the picture.
    originals = {a.original_id for a in meta.values() if a.original_id}
    ids = {i for i, a in meta.items() if a.produced_by is None and i not in originals}
    if any(step.tool not in registry.REGISTRY for step in data.steps):
        ids.update(meta)  # opaque tool parameters cannot authorize reachability pruning
    ids.update(data.creative.source_roles.values())
    for s in data.steps:
        ids.update(_image_refs(s), s.outputs, s.previous_outputs)
    named: set[str] = set()
    texts: list[str] = []
    for m in data.messages:
        named.update(m.step_ids)
        ids.update(p.artifact_id for p in m.content if p.type == "image" and p.artifact_id)
        texts.extend(p.text for p in m.content if p.text)
    ids.update(i for i, a in meta.items() if a.produced_by in named)
    by_short: dict[str, list[str]] = {}
    for i in meta:
        by_short.setdefault(short(i), []).append(i)
    for found in Session._mentioned([data.transcript, texts], set(by_short)):
        ids.update(by_short[found])
    for branch in [*data.branches.values(), *data.manual_undo, *data.manual_redo]:
        ids.update(branch.artifact_ids)
        ids.update(branch.creative.source_roles.values())
    pending = list(ids)
    while pending:
        item = meta.get(pending.pop())
        if item is None:
            continue
        for ref in (*item.inputs, *([item.original_id] if item.original_id else [])):
            if ref not in ids:
                ids.add(ref)
                pending.append(ref)
    return ids
