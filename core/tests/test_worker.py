"""The tool worker: wall-clock and memory limits, crashes, cancel, close (Task 10; review focus 5)."""

import hashlib
import io
import multiprocessing
import multiprocessing.connection
import os
import socket
import subprocess
import sys
import threading
import time

import psutil
import pytest
from PIL import Image

from badshop.engine import assets
from badshop.session import worker
from badshop.session.execution import InProcessExecutor, ToolCall
from badshop.session.worker import CRASH_HINT, LIMIT_HINT, TEST_TOOLS_ENV, WorkerExecutor
from badshop.tools import REGISTRY


@pytest.fixture
def test_tools(monkeypatch):
    monkeypatch.setenv(TEST_TOOLS_ENV, "1")  # read by each worker process when it starts


def call(tool: str, **params) -> ToolCall:
    return ToolCall(tool=tool, params=params, inputs={}, stem="")


def run_in_thread(w: WorkerExecutor, c: ToolCall) -> tuple[threading.Thread, list]:
    box: list = []
    t = threading.Thread(target=lambda: box.append(w.run(c)))
    t.start()
    return t, box


def assert_fresh_worker_works(w: WorkerExecutor, old_pid: int) -> None:
    out = w.run(call("_sleep"))
    assert out.ok and out.data["pid"] not in (old_pid, os.getpid())
    assert not psutil.pid_exists(old_pid)  # the old worker is gone, not left behind


def test_a_real_tool_gives_the_same_outcome_as_in_process():
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(buf, "PNG")
    data = buf.getvalue()
    aid = hashlib.sha256(data).hexdigest()
    c = ToolCall(tool="prep", params={"image": aid}, inputs={aid: data}, stem="pic")
    with WorkerExecutor() as w:
        out = w.run(c)
    assert out.ok and [o.key for o in out.outputs] == ["work", "grid"]
    with Image.open(io.BytesIO(out.outputs[0].data)) as im:
        assert im.size == (30, 20)
    assert out == InProcessExecutor().run(c)


def test_the_worker_starts_lazily_and_is_reused(test_tools):
    with WorkerExecutor() as w:
        assert w.pid is None
        a = w.run(call("_sleep"))
        b = w.run(call("_boom", engine=True))  # an EngineError is a normal failure: same worker
        c = w.run(call("_sleep"))
        assert a.ok and a.lines == ["slept 0 s"] and a.data["pid"] == w.pid != os.getpid()
        assert (b.ok, b.crashed, b.error_message, b.error_hint) == (False, False, "boom", "a test error")
        assert c.ok and c.data["pid"] == a.data["pid"]


def test_the_worker_drops_cached_rembg_sessions_under_memory_pressure(test_tools):
    with WorkerExecutor() as w:
        assert w.run(call("_sessions", put=True)).data["sessions"] == ["_test"]
        pid = w.pid
        assert w.run(call("_sessions")).data["sessions"] == ["_test"]  # kept: far below half of 3072 MB
        held_mb = psutil.Process(pid).memory_info().rss / 2**20
        # A tiny limit: the worker stays under it (the watchdog lets calls run) but holds more than half of it
        w.max_rss_mb = int(held_mb * 1.5)
        assert w.run(call("_sessions")).data["sessions"] == ["_test"]  # dropped after the call, not during it
        out = w.run(call("_sessions"))
        assert out.ok and out.data["sessions"] == [] and w.pid == pid  # the same worker: a drop is not a restart


FAILURES = [
    pytest.param("_sleep", {"seconds": 60}, {"timeout_s": 1.0},
                 "the tool took longer than 1 s and was stopped", LIMIT_HINT, False, id="hang"),
    pytest.param("_hog", {"mb": 800}, {"max_rss_mb": 400},
                 "the tool used more than 400 MB of memory and was stopped", LIMIT_HINT, False, id="memory"),
    pytest.param("_boom", {}, {}, "the tool crashed (RuntimeError: boom)", CRASH_HINT, True, id="exception"),
    pytest.param("_die", {"code": 3}, {}, "the tool's process died (exit code 3)", CRASH_HINT, True,
                 id="exit"),
    pytest.param("_die", {"how": "kill"}, {}, "the tool's process died (exit code -9)", CRASH_HINT, True,
                 id="killed", marks=pytest.mark.skipif(os.name != "posix", reason="POSIX signal exit code")),
]


@pytest.mark.parametrize("tool, params, limits, message, hint, crashed", FAILURES)
def test_a_failing_tool_fails_cleanly_and_the_next_call_gets_a_fresh_worker(
        test_tools, tool, params, limits, message, hint, crashed):
    with WorkerExecutor(**{"timeout_s": 20.0, **limits}) as w:
        first = w.run(call("_sleep")).data["pid"]
        t = time.monotonic()
        out = w.run(call(tool, **params))
        assert time.monotonic() - t < 15  # well short of the 60 s sleep and the 20 s default here
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (False, message, hint, crashed)
        assert out.outputs == [] and w.pid is None
        assert_fresh_worker_works(w, first)


def test_cancel_stops_the_running_call_and_is_a_no_op_when_idle(test_tools):
    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        w.cancel()  # nothing is running: the next call is not affected
        assert w.run(call("_sleep")).data["pid"] == first
        t, box = run_in_thread(w, call("_sleep", seconds=60))
        start = time.monotonic()
        while t.is_alive() and time.monotonic() - start < 10:
            w.cancel()  # a no-op until the call is running
            t.join(0.05)
        assert not t.is_alive()
        assert (box[0].ok, box[0].error_message, box[0].error_hint) == (False, "stopped by the user", None)
        assert_fresh_worker_works(w, first)


def test_a_call_whose_own_cancel_event_is_set_before_it_begins_is_never_sent(test_tools):
    stop = threading.Event()
    stop.set()  # Task 11's Stop landed while the step was still on its way to the executor
    with WorkerExecutor() as w:
        out = w.run(call("_sleep"), stop)
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (
            False, "stopped by the user", None, False)
        assert w.pid is None  # nothing to send, so no worker was started for it
        first = w.run(call("_sleep")).data["pid"]
        out = w.run(call("_die"), cancel=stop)  # had it been sent, the worker would have died
        assert out.error_message == "stopped by the user" and w.pid == first
        assert w.run(call("_sleep")).data["pid"] == first  # the same worker, untouched


def test_a_call_whose_own_cancel_event_is_set_while_it_runs_is_stopped(test_tools, monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(assets, "PROGRESS", lambda *event: stop.set())  # the tool is under way: stop it
    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        t = time.monotonic()
        out = w.run(call("_download", steps=1000, every_s=0.05), cancel=stop)  # 50 s if nothing stops it
        assert time.monotonic() - t < 15
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (
            False, "stopped by the user", None, False)
        assert out.outputs == [] and w.pid is None  # killed, exactly as cancel() kills it
        assert_fresh_worker_works(w, first)


def test_close_stops_the_worker_and_later_calls_fail_cleanly(test_tools):
    with WorkerExecutor() as w:  # leaving the block closes it a second time, which is fine
        pid = w.run(call("_sleep")).data["pid"]
        w.close()
        assert w.pid is None and not psutil.pid_exists(pid)
        out = w.run(call("_sleep"))
        assert (out.ok, out.error_message) == (False, "the tool worker is closed")


def test_close_stops_a_running_call(test_tools):
    with WorkerExecutor() as w:
        pid = w.run(call("_sleep")).data["pid"]
        t, box = run_in_thread(w, call("_sleep", seconds=60))
        w.close()
        t.join(10)
        assert not t.is_alive()
        # close() either stopped the call or got in before it started
        assert not box[0].ok and box[0].error_message in ("stopped by the user", "the tool worker is closed")
        assert not psutil.pid_exists(pid)


def test_a_worker_that_does_not_start_in_time_fails_cleanly(test_tools, monkeypatch):
    with WorkerExecutor(poll_s=0.001) as w:  # no Python process is ready 1 ms after it is spawned
        with monkeypatch.context() as m:
            m.setattr(worker, "STARTUP_TIMEOUT_S", 0.0)
            out = w.run(call("_sleep"))
        assert (out.ok, out.error_message, out.error_hint) == (
            False, "the tool worker did not start within 0 s", "try again")
        assert w.pid is None and w.run(call("_sleep")).ok


@pytest.mark.parametrize("step, errno, text", [
    ("pipe", 24, "Too many open files"),  # EMFILE: no file descriptors left for the pipe
    ("process", 11, "out of processes"),  # EAGAIN from fork/exec
])
def test_a_worker_that_cannot_be_spawned_fails_cleanly(test_tools, monkeypatch, step, errno, text):
    def refuse(*args):
        raise OSError(errno, text)

    ctx = multiprocessing.get_context("spawn")
    with WorkerExecutor() as w:
        with monkeypatch.context() as m:
            if step == "pipe":
                m.setattr(type(ctx), "Pipe", refuse)
            else:
                m.setattr(ctx.Process, "start", refuse)
            out = w.run(call("_sleep"))
        assert (out.ok, out.error_hint) == (False, "try again")
        assert out.error_message == f"the tool worker could not start ([Errno {errno}] {text})"
        assert w.pid is None and w.run(call("_sleep")).ok


def test_download_progress_reaches_the_core_and_does_not_count_against_the_clock(test_tools, monkeypatch):
    events = []
    monkeypatch.setattr(assets, "PROGRESS", lambda *a: events.append(a))
    with WorkerExecutor(timeout_s=1.5) as w:
        slow = w.run(call("_download", steps=6, every_s=0.3))  # 1.8 s in all, but progress every 0.3 s
        assert slow.ok and events == [("_download", i, 6) for i in range(1, 7)]
        events.clear()
        fast = w.run(call("_download", steps=50, every_s=0.001))  # forwarded at most every 0.1 s
        assert fast.ok and events[-1] == ("_download", 50, 50) and len(events) < 50
        events.clear()
        unsized = w.run(call("_download", steps=50, every_s=0.001, sized=False))  # no Content-Length
        assert unsized.ok and events[-1] == ("_download", 50, None) and len(events) < 50


def test_held_back_progress_goes_out_before_the_next_download_and_at_the_end(monkeypatch):
    monkeypatch.setattr(worker, "PROGRESS_EVERY_S", 3600.0)  # the throttle holds back every report
    core_end, worker_end = multiprocessing.Pipe()
    with core_end, worker_end:
        sender = worker._Sender(worker_end)
        for name, total in (("fonts/a.ttf", None), ("fonts/b.ttf", None), ("model.onnx", 3)):
            for done in (1, 2, 3):
                sender.progress(name, done, total)
        sender.flush()  # the worker flushes before it sends a call's outcome
        heard = []
        while core_end.poll():
            heard.append(core_end.recv())
    assert heard == [("progress", "fonts/a.ttf", 3, None), ("progress", "fonts/b.ttf", 3, None),
                     ("progress", "model.onnx", 3, 3)]


def test_a_call_interrupted_in_the_core_leaves_nothing_for_the_next_call(test_tools, monkeypatch):
    class Interrupted(BaseException):  # like KeyboardInterrupt, without its special handling in pytest
        pass

    def listener(*event):
        raise Interrupted

    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        with monkeypatch.context() as m:
            m.setattr(assets, "PROGRESS", listener)
            with pytest.raises(Interrupted):
                w.run(call("_download", steps=3, every_s=0))
        assert w.pid is None  # the unread "downloaded 3 chunks" outcome went with the worker
        assert w.run(call("_sleep")).lines == ["slept 0 s"]
        assert_fresh_worker_works(w, first)


@pytest.mark.skipif(os.name != "posix", reason="emulates a Windows pipe on a POSIX socketpair")
def test_a_pipe_that_breaks_while_polling_means_the_worker_died(test_tools, monkeypatch):
    # On Windows, polling a pipe whose other end has closed raises BrokenPipeError instead of reporting
    # EOF (the [exit] case above meets the real thing there). Emulate that here.
    real_poll = multiprocessing.connection.Connection.poll

    def windows_poll(conn, timeout=0.0):
        if not real_poll(conn, timeout):
            return False
        with socket.socket(fileno=os.dup(conn.fileno())) as s:
            if s.recv(1, socket.MSG_PEEK) == b"":  # EOF: the worker's end is closed
                raise BrokenPipeError(32, "The pipe has been ended")
        return True

    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        monkeypatch.setattr(multiprocessing.connection.Connection, "poll", windows_poll)
        out = w.run(call("_die"))
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (
            False, "the tool's process died (exit code 3)", CRASH_HINT, True)
        assert_fresh_worker_works(w, first)


CORE_SCRIPT = """\
from badshop.session.execution import ToolCall
from badshop.session.worker import WorkerExecutor

if __name__ == "__main__":
    w = WorkerExecutor()
    print(w.run(ToolCall(tool="_sleep", params={}, inputs={}, stem="")).data["pid"], flush=True)
    w.run(ToolCall(tool="_sleep", params={"seconds": 60}, inputs={}, stem=""))
"""


def test_a_worker_whose_core_dies_exits_too(test_tools, tmp_path):
    script = tmp_path / "core.py"
    script.write_text(CORE_SCRIPT)
    with subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True) as core:
        worker_process = psutil.Process(int(core.stdout.readline()))
        core.kill()  # mid-call, the way a crash or the shell ends the core
    try:
        worker_process.wait(timeout=10)  # psutil.TimeoutExpired if the worker outlives its core
    finally:
        if worker_process.is_running():
            worker_process.kill()


def test_what_a_tool_prints_goes_to_stderr_not_the_cores_stdout(test_tools, capfd):
    with WorkerExecutor() as w:
        assert w.run(call("_sleep", say="noise from a tool")).ok
    out, err = capfd.readouterr()
    assert "noise from a tool" not in out and "noise from a tool" in err


def test_pillows_size_warning_stays_out_of_the_log(capfd):
    buf = io.BytesIO()
    Image.new("1", (10000, 9000)).save(buf, "PNG")  # 90 Mpx, past Pillow's warning line; a few KB as PNG
    data = buf.getvalue()
    aid = hashlib.sha256(data).hexdigest()
    with WorkerExecutor() as w:
        out = w.run(ToolCall(tool="info", params={"image": aid}, inputs={aid: data}, stem="big"))
    assert out.ok and out.data == {"width": 10000, "height": 9000}  # the image really was opened
    assert "DecompressionBombWarning" not in capfd.readouterr().err


def test_the_test_tools_need_the_env_var(monkeypatch):
    monkeypatch.delenv(TEST_TOOLS_ENV, raising=False)
    test_only = {"_sleep", "_hog", "_boom", "_die", "_download", "_sessions"}
    assert not test_only & set(REGISTRY)  # the core never has them
    with WorkerExecutor() as w:
        out = w.run(call("_die"))
    assert (out.ok, out.crashed, out.error_message) == (False, False, "unknown tool '_die'")


@pytest.mark.skipif(not hasattr(psutil.Process, "num_fds"), reason="counts POSIX file descriptors")
def test_restarts_do_not_leak_file_descriptors(test_tools):
    me = psutil.Process()
    with WorkerExecutor() as w:
        assert w.run(call("_sleep")).ok  # the first spawn may open lasting helpers (the resource tracker)
        before = me.num_fds()
        for _ in range(3):
            assert w.run(call("_die")).crashed
            assert w.run(call("_sleep")).ok
        assert me.num_fds() == before
