"""Tool calls in a worker process, with a wall-clock limit, a memory limit, cancel and restart.

A runaway loop, a memory blow-up or a native crash in a tool takes down only the worker: the step fails
with a clean error and the next call starts a fresh worker (carry-forward SEC-S4; spec §5.4's "cancel at
the next safe point"). The memory limit is an RSS watchdog, not RLIMIT_AS (under a 4 GB `ulimit -v`,
`import cv2` segfaults), so it works the same way on Linux, macOS and Windows. The limits live in the
core, so a worker whose core has died exits on its own.

Asset downloads inside a tool (the first cutout fetches its model) report progress to the core's
`assets.PROGRESS` through the pipe, and each report pushes the deadline back to a full `timeout_s`:
downloading is not the tool's time, and a slow connection must not kill every first cutout.

Between calls, a worker that holds more than half of the memory limit drops its cached rembg session
(carry-forward TRI T7 F3), so a cache never leaves the next call too little room.

A call can carry its own stop signal (`run(call, cancel)`, the agent's Stop): set before the call
begins, it is never sent; set while it runs, the worker is killed, as `cancel()` kills it.

The worker is a `spawn` child: a script that creates a WorkerExecutor needs an
`if __name__ == "__main__":` guard (`python -m badshop.server` and console scripts are fine), and a
frozen build must call `multiprocessing.freeze_support()` first.
"""

import multiprocessing
import multiprocessing.connection
import os
import signal
import threading
import time
import warnings
from typing import Literal, NoReturn

import psutil
from PIL import Image
from pydantic import Field

from badshop.engine import assets, cutout
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params
from badshop.session.execution import CRASH_HINT, STOPPED, ToolCall, ToolOutcome, execute_call
from badshop.tools.registry import ToolSpec, register  # importing badshop.tools registers every tool

TEST_TOOLS_ENV = "BADSHOP_WORKER_TEST_TOOLS"  # "1": the worker also registers the test tools below
STARTUP_TIMEOUT_S = 60.0  # spawning Python and importing the tools; not counted against the tool
CHILDREN_EVERY_S = 1.0  # listing the worker's own subprocesses scans every process, so do it sparingly
PROGRESS_EVERY_S = 0.1  # the worker forwards download progress at most this often, plus the last chunk
STOP_WAIT_S = 5.0
LIMIT_HINT = "try smaller parameters or a smaller image"


def _failed(message: str, hint: str | None = None, crashed: bool = False) -> ToolOutcome:
    return ToolOutcome(ok=False, error_message=message, error_hint=hint, crashed=crashed)


def _report_progress(name: str, done: int, total: int | None) -> None:
    listener = assets.PROGRESS
    if listener is not None:
        try:
            listener(name, done, total)
        except Exception:  # a broken listener (say, the server shutting down) must not fail the tool
            pass


class _Stopped(Exception):
    """The worker was stopped or died; `outcome` is what the caller gets."""

    def __init__(self, outcome: ToolOutcome):
        super().__init__(outcome.error_message)
        self.outcome = outcome


class WorkerExecutor:
    """Runs ToolCalls in one reusable worker process, spawned on the first call.

    `run` serves one caller at a time (others wait); `cancel` and `close` may be called from any thread,
    and so may a call's own cancel event be set. `timeout_s`, `max_rss_mb` and `poll_s` are read on
    every call."""

    def __init__(self, timeout_s: float = 120.0, max_rss_mb: int = 3072, poll_s: float = 0.05):
        self.timeout_s = timeout_s
        self.max_rss_mb = max_rss_mb
        self.poll_s = poll_s
        self._ctx = multiprocessing.get_context("spawn")  # fork would copy the core's threads and sockets
        self._proc = None
        self._conn = None
        self._pid: int | None = None
        self._ps: psutil.Process | None = None
        self._kids: list[psutil.Process] = []
        self._kids_at = 0.0
        self._call_lock = threading.Lock()  # one run at a time
        self._state = threading.Lock()  # makes close() atomic with run()'s closed check and cancel reset
        self._closed = False
        self._cancel = threading.Event()

    @property
    def pid(self) -> int | None:
        """The worker's process id, or None while there is no worker."""
        return self._pid

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome:
        """Run one call in the worker. `cancel` is this call's own stop signal: already set when the call's
        turn comes, the call is never sent and the worker is left as it is; set while it runs, the worker
        is killed, as for cancel(). Either way the outcome says "stopped by the user"."""
        with self._call_lock:
            with self._state:
                if self._closed:
                    return _failed("the tool worker is closed")
                self._cancel.clear()  # a cancel() from before this call is not for it
            if cancel is not None and cancel.is_set():  # stopped before it began: the tool never runs
                return _failed(STOPPED)
            return self._run(call, cancel)

    def cancel(self) -> None:
        """Stop the running call; its outcome says "stopped by the user". Does nothing when idle, so it
        can't reach a call that hasn't entered run() yet: a caller that must stop one particular call
        passes that call's own event to run()."""
        self._cancel.set()

    def close(self) -> None:
        """Stop any running call and the worker. Later calls fail with "the tool worker is closed"."""
        with self._state:
            self._closed = True
            self._cancel.set()
        with self._call_lock:
            self._stop_worker(graceful=True)

    def __enter__(self) -> "WorkerExecutor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _run(self, call: ToolCall, cancel: threading.Event | None) -> ToolOutcome:
        try:
            if self._proc is None or not self._proc.is_alive():
                self._start(cancel)
            try:
                self._conn.send((call, self.max_rss_mb))  # the worker drops cached models above half of it
            except OSError:  # the worker died between calls
                self._died()
            outcome = self._receive(time.monotonic() + self.timeout_s, _failed(
                f"the tool took longer than {self.timeout_s:g} s and was stopped", LIMIT_HINT), cancel)
        except _Stopped as s:
            return s.outcome
        except BaseException:
            # Interrupted in the core (a progress listener raised KeyboardInterrupt, unpickling ran out of
            # memory): this call's outcome may still be on its way, and the next call must not read it.
            self._stop_worker()
            raise
        if outcome.crashed:  # an exception other than EngineError: don't trust this process again
            self._stop_worker()
        return outcome

    def _start(self, cancel: threading.Event | None) -> None:
        self._stop_worker()  # release a worker that died between calls
        parent = child = None
        try:
            parent, child = self._ctx.Pipe()
            proc = self._ctx.Process(target=_worker_main, args=(child,), name="badshop-worker", daemon=True)
            proc.start()
        except OSError as e:  # out of file descriptors, processes or memory
            if parent is not None:
                parent.close()
            raise _Stopped(_failed(f"the tool worker could not start ({e})", "try again")) from None
        finally:
            if child is not None:
                child.close()  # the worker holds the only other end, so its death reads as EOF here
        self._proc, self._conn, self._pid = proc, parent, proc.pid
        try:
            self._ps = psutil.Process(proc.pid)
        except psutil.Error:  # already gone: _receive reports how it died
            self._ps = None
        self._kids, self._kids_at = [], time.monotonic()
        self._receive(time.monotonic() + STARTUP_TIMEOUT_S,
                      _failed(f"the tool worker did not start within {STARTUP_TIMEOUT_S:g} s", "try again"),
                      cancel)

    def _receive(self, deadline: float, late: ToolOutcome, cancel: threading.Event | None):
        """The worker's next message other than download progress, which goes to assets.PROGRESS and
        moves the deadline. On cancel() or the call's own `cancel` event, the deadline, the memory limit
        or the worker's death, the worker is stopped and _Stopped carries the outcome."""
        while True:
            try:
                ready = self._conn.poll(self.poll_s)
                message = self._conn.recv() if ready else None
            except (EOFError, OSError):  # the worker's end closed (on Windows, poll itself raises)
                self._died()
            if ready:
                if not (isinstance(message, tuple) and message[:1] == ("progress",)):
                    return message
                _report_progress(*message[1:])
                deadline = max(deadline, time.monotonic() + self.timeout_s)
            elif not self._proc.is_alive():
                self._died()
            if self._cancel.is_set() or (cancel is not None and cancel.is_set()):
                self._kill(_failed(STOPPED))
            if time.monotonic() >= deadline:
                self._kill(late)
            if self._rss_mb() > self.max_rss_mb:
                self._kill(_failed(f"the tool used more than {self.max_rss_mb} MB of memory and was stopped",
                                   LIMIT_HINT))

    def _rss_mb(self) -> float:
        """Resident memory of the worker and its own subprocesses, in MB."""
        if self._ps is None:
            return 0.0
        now = time.monotonic()
        if now - self._kids_at >= CHILDREN_EVERY_S:
            try:
                self._kids = self._ps.children(recursive=True)
            except psutil.Error:
                self._kids = []
            self._kids_at = now
        total = 0
        for p in (self._ps, *self._kids):
            try:
                total += p.memory_info().rss
            except psutil.Error:  # exited since the last listing
                pass
        return total / 2**20

    def _died(self) -> NoReturn:
        self._proc.join(STOP_WAIT_S)  # the pipe can close a moment before the exit status is ready
        code = self._stop_worker()
        raise _Stopped(_failed(f"the tool's process died (exit code {code})", CRASH_HINT, crashed=True))

    def _kill(self, outcome: ToolOutcome) -> NoReturn:
        self._stop_worker()
        raise _Stopped(outcome)

    def _stop_worker(self, graceful: bool = False) -> int | None:
        """End the worker (asking it to exit first when graceful), release it, return its exit code."""
        proc, conn, ps = self._proc, self._conn, self._ps
        self._proc = self._conn = self._ps = self._pid = None
        self._kids = []
        if proc is None:
            return None
        if graceful and proc.is_alive():
            try:
                conn.send(None)
                proc.join(STOP_WAIT_S)
            except OSError:
                pass
        if proc.is_alive():
            try:
                kids = ps.children(recursive=True) if ps is not None else []
            except psutil.Error:
                kids = []
            for k in kids:
                try:
                    k.kill()
                except psutil.Error:
                    pass
            proc.kill()
            proc.join(STOP_WAIT_S)
        code = proc.exitcode
        conn.close()
        if code is not None:  # Process.close() refuses a process that is somehow still running
            proc.close()
        return code


class _Sender:
    """The worker's end of the pipe: one lock for every message, and throttled download progress.

    A report the throttle holds back is sent when another download starts or by flush(), which runs
    before each call's outcome, so the core always hears a download's last chunk (even when the size
    is unknown, so no chunk has done == total)."""

    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.Lock()
        self.last = time.monotonic()  # when a progress report was last sent
        self.held: tuple | None = None  # the latest report the throttle held back

    def __call__(self, message) -> None:
        with self.lock:
            self.conn.send(message)

    def progress(self, name: str, done: int, total: int | None) -> None:
        message = ("progress", name, done, total)
        with self.lock:
            if self.held is not None and self.held[1] != name:  # another download: finish the last one
                self.conn.send(self.held)
            self.held = message
            now = time.monotonic()
            if done == total or now - self.last >= PROGRESS_EVERY_S:
                self.conn.send(message)
                self.last, self.held = now, None

    def flush(self) -> None:
        with self.lock:
            if self.held is not None:
                self.conn.send(self.held)
                self.held = None


def _exit_with_the_core(core_sentinel) -> None:
    """Runs on a daemon thread in the worker. The time and memory limits live in the core, so when the
    core ends (a crash, the shell killing it) the worker must not keep running a tool unwatched, or
    overlap with the worker of a restarted core. The sentinel becomes ready when the core exits, on
    POSIX and on Windows."""
    multiprocessing.connection.wait([core_sentinel])
    os._exit(1)


def _drop_sessions_under_pressure(me: psutil.Process, max_rss_mb: float) -> None:
    """Runs in the worker after each call (carry-forward TRI T7 F3: drop cached sessions under memory
    pressure). The cached rembg session is the one big thing the worker keeps between calls; once the
    worker holds more than half of the core's limit, the next call would have less than half to work in,
    so free the session and let the next cutout rebuild it (0.3 to 0.6 s for u2net)."""
    try:
        held_mb = me.memory_info().rss / 2**20
    except psutil.Error:
        return
    if held_mb > max_rss_mb / 2:
        cutout.drop_sessions()


def _worker_main(conn) -> None:
    """The worker process. The tools are already imported (this module's imports); run calls until told
    to stop or until the core goes away."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl-C in a terminal reaches us too; the core stops us
    try:
        os.dup2(2, 1)  # the core's stdout carries its handshake line: whatever a tool prints goes to stderr
    except OSError:
        pass
    # Pillow warns about 89-179 Mpx images before our own size checks refuse them (carry-forward);
    # one tool at a time runs here, so a process-wide filter is safe where catch_warnings is not.
    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
    core = multiprocessing.parent_process()
    if core is not None:  # always, in a spawned worker
        threading.Thread(target=_exit_with_the_core, args=(core.sentinel,), name="badshop-core-watch",
                         daemon=True).start()
    send = _Sender(conn)
    assets.PROGRESS = send.progress  # downloads inside a tool report to the core's listener
    if os.environ.get(TEST_TOOLS_ENV) == "1":
        _register_test_tools()
    me = psutil.Process()
    send("ready")
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            return
        if message is None:
            return
        call, max_rss_mb = message  # the core's memory limit, as it read it for this call
        outcome = execute_call(call)
        send.flush()
        send(outcome)
        del message, call, outcome  # count what the worker keeps between calls, not this call's images
        _drop_sessions_under_pressure(me, max_rss_mb)


# Test-only tools: they misbehave on purpose. Only a worker whose environment has
# BADSHOP_WORKER_TEST_TOOLS=1 registers them; the core's own registry never has them.

class _SleepParams(Params):
    seconds: float = Field(0.0, ge=0, le=3600)
    say: str = Field("", max_length=200, description="printed to stdout before sleeping")


class _HogParams(Params):
    mb: int = Field(ge=1, le=65536)
    hold_s: float = Field(30.0, ge=0, le=3600)


class _BoomParams(Params):
    engine: bool = False  # raise EngineError instead of RuntimeError


class _DieParams(Params):
    code: int = Field(3, ge=0, le=255)
    how: Literal["exit", "kill"] = "exit"  # os._exit(code), or kill the process with a signal


class _DownloadParams(Params):
    steps: int = Field(ge=1, le=10000)
    every_s: float = Field(ge=0, le=60)
    sized: bool = True  # report the total, as cached() does when the response has a Content-Length


class _SessionsParams(Params):
    put: bool = False  # cache a stand-in rembg session first


def _sleep(p: _SleepParams, store) -> EngineResult:
    if p.say:
        print(p.say, flush=True)
    time.sleep(p.seconds)
    return EngineResult(lines=[f"slept {p.seconds:g} s"], data={"pid": os.getpid()})


def _hog(p: _HogParams, store) -> EngineResult:
    block = b"x" * (p.mb * 2**20)  # filled, so every page is really resident
    time.sleep(p.hold_s)
    return EngineResult(lines=[f"held {len(block) // 2**20} MB"])


def _boom(p: _BoomParams, store) -> EngineResult:
    if p.engine:
        raise EngineError("boom", hint="a test error")
    raise RuntimeError("boom")


def _die(p: _DieParams, store) -> EngineResult:
    if p.how == "kill":
        os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
    os._exit(p.code)


def _download(p: _DownloadParams, store) -> EngineResult:
    """Reports progress the way assets.cached does, without the network."""
    for i in range(1, p.steps + 1):
        time.sleep(p.every_s)
        if assets.PROGRESS is not None:
            assets.PROGRESS("_download", i, p.steps if p.sized else None)
    return EngineResult(lines=[f"downloaded {p.steps} chunks"])


def _sessions(p: _SessionsParams, store) -> EngineResult:
    """The worker's cached rembg sessions, by model (with put, after caching a stand-in one)."""
    if p.put:
        cutout._SESSIONS["_test"] = object()
    return EngineResult(data={"sessions": sorted(cutout._SESSIONS)})


def _register_test_tools() -> None:
    for name, params, fn in (("_sleep", _SleepParams, _sleep), ("_hog", _HogParams, _hog),
                             ("_boom", _BoomParams, _boom), ("_die", _DieParams, _die),
                             ("_download", _DownloadParams, _download),
                             ("_sessions", _SessionsParams, _sessions)):
        register(ToolSpec(name=name, params=params, run=fn, summary=f"worker test tool {name}",
                          description="Misbehaves on purpose for tests/test_worker.py.", category="test",
                          mutates=False, read_only=True))
