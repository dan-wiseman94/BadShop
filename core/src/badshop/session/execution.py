"""The tool-call boundary. A ToolCall carries everything one tool run needs (validated JSON params and
the bytes of every input artifact); a ToolOutcome carries everything it made. Both are plain picklable
data, so a call runs the same in this process or in a worker process (session/worker.py)."""

import hashlib
import json
import platform
import threading
import sys
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError, features

import badshop
from badshop.build_identity import build_identity
from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.session import netpolicy
from badshop.session.artifacts import IMPORT_FORMATS, MAX_IMPORT_PIXELS, REF_HINT, _decode, _frames, _refused
from badshop.tools import runner

CRASH_HINT = "this is a bug in badshop; other steps are unaffected"
STOPPED = "stopped by the user"  # a stopped call's error_message, whichever executor stopped it


@dataclass(frozen=True)
class ToolCall:
    tool: str
    params: dict  # JSON-safe and already validated (with the proposing actor); image refs are full ids
    inputs: dict[str, bytes]  # every artifact id the params reference -> its bytes
    stem: str  # the label stem outputs are named from (the first input's label), for runner.execute
    trusted_urls: frozenset[str] = frozenset()  # links the user typed (netpolicy.typed_urls)
    guard_network: bool = True  # run under netpolicy.guarded(trusted_urls)
    no_remote: bool = False


@dataclass(frozen=True)
class DecodeCall:
    """Untrusted compressed bytes enter only the existing bounded worker boundary."""
    data: bytes
    name: str
    frame: int = 0


@dataclass(frozen=True)
class MediaCall:
    """User-picked media extraction and collection indexing need the same process limits."""
    operation: str
    root: str
    params: dict


@dataclass
class OutputRecord:
    key: str  # "work", "cutout", "1", "sheet"...
    data: bytes  # Output.encode(): exactly the artifact's bytes
    name_hint: str  # as the tool gave it ("{stem}_work.png", "final:{stem}"); the session makes the label
    caption: str = ""


@dataclass
class ToolOutcome:
    ok: bool
    outputs: list[OutputRecord] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)  # tool results are JSON-safe; decode replies carry raw bytes
    error_message: str | None = None
    error_hint: str | None = None
    crashed: bool = False  # a bug (not an EngineError): the session reports it the same way


def execute_decode(call: DecodeCall) -> ToolOutcome:
    try:
        with _decode(call.data, call.name) as image:
            frames = _frames(image, call.name)
            if not 0 <= call.frame < frames:
                raise EngineError("frame is outside this animation")
            if call.frame:
                image.seek(call.frame)
                image.load()
            # Raw pixels cross back. The core never reopens hostile compressed bytes.
            data = {"mode": image.mode, "size": image.size, "format": image.format, "frames": frames,
                    "pixels": image.tobytes(), "info": image.info,
                    "palette": image.getpalette() if image.mode in ("P", "PA") else None}
            return ToolOutcome(ok=True, data=data)
    except EngineError as error:
        return ToolOutcome(ok=False, error_message=error.message, error_hint=error.hint)
    except Exception as error:
        refused = _refused(call.name, error)
        return ToolOutcome(ok=False, error_message=refused.message, error_hint=refused.hint)


def decoded_image(outcome: ToolOutcome) -> Image.Image:
    if not outcome.ok:
        raise EngineError(outcome.error_message or "could not decode image", hint=outcome.error_hint)
    data = outcome.data
    image = Image.frombytes(data["mode"], data["size"], data["pixels"])
    if data["palette"] is not None:
        image.putpalette(data["palette"])
    image.info = data["info"]
    image.format = data["format"]
    image.n_frames = data["frames"]
    return image


def execute_media(call: MediaCall) -> ToolOutcome:
    from badshop.session.local_collection import LocalCollections
    from badshop.session.media import MediaSources

    try:
        if call.operation == "preview":
            result = MediaSources(call.root).preview(**call.params)
        elif call.operation == "index":
            result = LocalCollections(call.root).index(**call.params)
        else:
            raise EngineError("unknown media operation")
        return ToolOutcome(ok=True, data=result)
    except EngineError as error:
        return ToolOutcome(ok=False, error_message=error.message, error_hint=error.hint)
    except Exception:
        return ToolOutcome(ok=False, error_message="source could not be decoded",
                           error_hint="choose a supported image, PDF, GIF or video", crashed=True)


class BytesStore:
    """A Store over one call's input bytes: load() decodes a fresh image each time (the web and import
    formats only, so a hostile project file can't pick Pillow's EPS decoder, which runs Ghostscript),
    put() keeps each output encoded, and export() is refused: only the session writes files."""

    def __init__(self, inputs: dict[str, bytes]):
        self.inputs = inputs
        self.outputs: list[OutputRecord] = []

    def load(self, ref: str) -> Image.Image:
        if ref not in self.inputs:
            raise EngineError(f"no such artifact: {ref}", hint=REF_HINT)
        try:
            return load_image(self.inputs[ref], formats=IMPORT_FORMATS, max_pixels=MAX_IMPORT_PIXELS)
        except Exception as e:  # hostile bytes make a decoder raise almost anything (ValueError, SyntaxError...)
            detail = "" if isinstance(e, UnidentifiedImageError) else f" ({e})"  # "cannot identify" names a BytesIO
            raise EngineError(f"artifact {ref[:8]} can't be read as an image{detail}",
                              hint="import the picture again") from None

    def put(self, output: Output, stem: str) -> str:
        self.outputs.append(OutputRecord(output.key, output.encode(), output.name_hint, output.caption))
        return f"out:{len(self.outputs) - 1}"

    def export(self, ref: str, name: str | None) -> str:
        raise EngineError("export runs in the session",
                          hint="tools that write files (writes_files) run in the session, not in a ToolCall")


def json_safe(data: dict) -> dict:
    """A tool's data as strict JSON: tuples become lists, values JSON has no type for (a Path) become
    their str(), and non-finite floats (NaN, inf, -inf, numpy's too) become None. json.dumps writes those
    floats as bare NaN/Infinity, which JavaScript's JSON.parse refuses; parse_constant is what json.loads
    calls for exactly those three tokens, never for a quoted "NaN"."""
    return json.loads(json.dumps(data, default=str), parse_constant=lambda _: None)


def execute_call(call: ToolCall) -> ToolOutcome:
    """Validate and run one call. An EngineError is a failed step the user or the model can act on; any
    other exception is a crash, reported as a clean message (never a traceback). A failed call keeps
    nothing it made."""
    store = BytesStore(call.inputs)
    try:
        params = runner.validate(call.tool, call.params)  # as "user": the session already checked the actor
        with netpolicy.guarded(call.trusted_urls, call.no_remote) if call.guard_network or call.no_remote else nullcontext():
            run = runner.execute(call.tool, params, store, stem=call.stem)
        data = json_safe(run.result.data)
        return ToolOutcome(ok=True, outputs=store.outputs, lines=list(run.result.lines), data=data)
    except EngineError as e:
        return ToolOutcome(ok=False, error_message=e.message, error_hint=e.hint, data=json_safe(e.data))
    except Exception as e:
        return ToolOutcome(ok=False, crashed=True, error_hint=CRASH_HINT,
                           error_message=f"the tool crashed ({type(e).__name__}: {e})")


@lru_cache(maxsize=1)
def runtime_fingerprint() -> dict:
    """A lockfile/codec/platform change can change pixels or encoded artifact IDs."""
    libraries = {}
    for package in ("pillow", "numpy", "opencv-python-headless", "onnxruntime", "rembg"):
        try:
            libraries[package] = version(package)
        except PackageNotFoundError:
            libraries[package] = "unavailable"
    return {"platform": sys.platform, "machine": platform.machine(), "libraries": libraries,
            "codecs": {name: features.version(name) for name in
                       ("zlib", "zlib_ng", "jpg", "libjpeg_turbo", "webp")}}


def cache_key(tool: str, params: dict) -> str:
    """Identifies one execution: the engine build/runtime, tool and stored params. Image refs in
    stored params are full artifact ids (content hashes), so the key covers the input bytes too."""
    blob = json.dumps({"engine": badshop.__version__, "build": build_identity(), "runtime": runtime_fingerprint(),
                       "tool": tool, "params": params},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


@runtime_checkable
class Executor(Protocol):
    """Runs ToolCalls: InProcessExecutor here, WorkerExecutor (session/worker.py) in a child process.

    `cancel` is one call's own stop signal (the agent's Stop hands one to each step it runs). Set before
    the call begins, the tool never runs; set while it runs, an executor that can stop a tool stops it.
    Either way the outcome is `ok=False` with `error_message=STOPPED`, not a crash. `cancel()` stops the
    call running at that moment, for callers with no event of their own (the server's shutdown); it
    can't reach a call that hasn't begun."""

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class InProcessExecutor:
    """Runs each call in this process, for tests and embedding: no time or memory limit, and once a tool
    has begun neither its cancel event nor cancel() can stop it (WorkerExecutor can). A call whose event
    is already set never runs."""

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome:
        if cancel is not None and cancel.is_set():  # stopped before it began
            return ToolOutcome(ok=False, error_message=STOPPED)
        return execute_call(call)

    def decode(self, data: bytes, name: str, frame: int = 0) -> Image.Image:
        return decoded_image(execute_decode(DecodeCall(data, name, frame)))

    def media(self, operation: str, root: str, *, cancel: threading.Event | None = None, **params) -> dict:
        if cancel is not None and cancel.is_set():
            raise EngineError(STOPPED)
        result = execute_media(MediaCall(operation, root, params))
        if not result.ok:
            raise EngineError(result.error_message or "source could not be decoded", hint=result.error_hint)
        return result.data

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        pass
