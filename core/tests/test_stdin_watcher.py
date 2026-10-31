"""Windows stdin polling never leaves a pending read on an empty inherited pipe."""

import ctypes
import sys
import time
from types import SimpleNamespace

import pytest

from badshop.server import main as core_main


@pytest.fixture
def windows_pipe(monkeypatch):
    class Operation:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)
    state = SimpleNamespace(kind=3, polls=[], reads=[], sleeps=[], error=0)
    kernel = SimpleNamespace(GetFileType=Operation(lambda _: state.kind))
    def peek(handle, buffer, size, read, available, remaining):
        assert handle == 2**40 and buffer is None and size == 0
        count, error = state.polls.pop(0)
        available._obj.value = count
        state.error = error
        return error == 0
    kernel.PeekNamedPipe = Operation(peek)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda _: 2**40))
    def dll(name, **kwargs):
        assert name == "kernel32" and kwargs == {"use_last_error": True}
        return kernel
    monkeypatch.setattr(ctypes, "WinDLL", dll, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: state.error, raising=False)
    monkeypatch.setattr(time, "sleep", state.sleeps.append)
    def read(fd, count):
        state.reads.append(count)
        return b"x" * count
    monkeypatch.setattr(core_main.os, "read", read)
    return state, kernel


def test_windows_pipe_polls_until_bytes_or_broken_pipe(windows_pipe):
    state, kernel = windows_pipe
    state.polls = [(0, 0), (3, 0), (0, 109)]
    assert core_main._windows_pipe_eof(0, lambda: False) is True
    assert state.reads == [3] and state.sleeps == [.05]
    assert kernel.PeekNamedPipe.argtypes[0] is ctypes.wintypes.HANDLE


@pytest.mark.parametrize("error", [109, 233])
def test_windows_pipe_disconnect_is_eof(windows_pipe, error):
    state, _ = windows_pipe
    state.polls = [(0, error)]
    assert core_main._windows_pipe_eof(0, lambda: False) is True
    assert state.reads == []


def test_windows_pipe_unreadable_is_not_a_blocking_fallback(windows_pipe):
    state, _ = windows_pipe
    state.polls = [(0, 5)]
    assert core_main._windows_pipe_eof(0, lambda: False) is False
    assert state.reads == []


def test_windows_regular_file_keeps_the_regular_eof_path(windows_pipe):
    state, _ = windows_pipe
    state.kind = 1  # FILE_TYPE_DISK
    assert core_main._windows_pipe_eof(0, lambda: False) is None
    assert state.reads == []


def test_windows_pipe_watcher_exits_when_core_stops(windows_pipe):
    state, _ = windows_pipe
    assert core_main._windows_pipe_eof(0, lambda: True) is False
    assert state.reads == []
