"""The terminal uses the real dispatcher, session and approval loop, without a paid provider."""

import asyncio
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest
from PIL import Image

from badshop.agent.fake import ScriptedProvider
from badshop.agent.provider import Reply, ToolCallRequest
from badshop.cli.chat import TerminalClient, user_path
from badshop.cli.main import build_parser
from badshop.engine.errors import EngineError
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.session.execution import InProcessExecutor


@pytest.fixture
def private_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "out"))
    monkeypatch.delenv("BADSHOP_FAKE_PROVIDER", raising=False)
    return tmp_path


def reader(lines):
    values = iter(lines)

    async def read(prompt):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


def app():
    return CoreApp(Settings(), executor_factory=lambda **kw: InProcessExecutor())


def test_terminal_import_approve_edit_save_open(private_env):
    photo = private_env / "test image.png"
    Image.new("RGB", (8, 8), "red").save(photo)
    saved = private_env / "my session.badshop"
    output = io.StringIO()

    async def run():
        core = app()
        client = TerminalClient(core, output=output)
        imported = await client.rpc("artifacts.import", path=str(photo))
        aid = imported["working"]["id"]
        core._provider = ScriptedProvider([
            Reply(text="Making it strange.", tool_calls=[ToolCallRequest(
                "c1", "filter", {"image": aid, "names": ["invert"]})]), Reply(text="Done.")])
        client.read = reader([
            "invert it", "e", "[]", "e", '{"image":"missing","names":["invert"]}',
            "e", json.dumps({"image": aid, "names": ["grayscale"]}),
            f"/save {saved}", f"/open {saved}", "/quit"])
        assert await client.run(build_parser().parse_args(["chat"])) == 0
        assert core._closed
        step = core.session.data.steps[0]
        assert step.status == "done"
        assert step.params["names"] == ["grayscale"]
        assert core.session.data.messages[-1].content[0].text == "Done."

    asyncio.run(run())
    text = output.getvalue()
    assert "Making it strange." in text and "Done." in text
    assert "invalid JSON parameters" in text and "no such artifact" in text
    assert f"Saved {saved}" in text and "Session opened." in text
    assert saved.exists()


def test_terminal_empty_approval_rejects_and_eof_closes(private_env):
    async def run():
        core = app()
        core._provider = ScriptedProvider([
            Reply(tool_calls=[ToolCallRequest("c1", "fetch", {"query": "never fetched"})]),
            Reply(text="Rejected.")])
        client = TerminalClient(core, read=reader(["do it", ""]), output=io.StringIO())
        assert await client.run(build_parser().parse_args(["chat"])) == 0
        assert core._closed and core.gate.pending() == []
        assert core.session.data.steps[0].status == "rejected"

    asyncio.run(run())


def test_terminal_eof_while_approving_stops_turn(private_env):
    async def run():
        core = app()
        core._provider = ScriptedProvider([
            Reply(tool_calls=[ToolCallRequest("c1", "fetch", {"query": "never fetched"})])])
        client = TerminalClient(core, read=reader(["do it"]), output=io.StringIO())
        assert await client.run(build_parser().parse_args(["chat"])) == 0
        assert core._closed and core._turn is None and core.gate.pending() == []
        assert core.session.data.steps[0].status == "rejected"

    asyncio.run(run())


def test_terminal_cancel_stops_turn(private_env):
    async def run():
        waiting = asyncio.Event()
        core = app()
        core._provider = ScriptedProvider([
            Reply(tool_calls=[ToolCallRequest("c1", "fetch", {"query": "never fetched"})])])

        async def read(prompt):
            if prompt == "badshop> ":
                return "do it"
            waiting.set()
            await asyncio.Future()

        client = TerminalClient(core, read=read, output=io.StringIO())
        task = asyncio.create_task(client.run(build_parser().parse_args(["chat"])))
        await asyncio.wait_for(waiting.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert core._closed and core._turn is None and core.gate.pending() == []

    asyncio.run(run())


def test_chat_parser_and_model_setup(private_env):
    args = build_parser().parse_args([
        "chat", "--model", "openai/custom", "--api-base", "http://localhost:1234/v1",
        "--api-key-env", "BADSHOP_TEST_KEY", "--supports-vision", "--supports-tools",
        "--approval-mode", "ask_all"])

    async def run():
        core = app()
        client = TerminalClient(core, read=reader(["/quit"]), output=io.StringIO())
        assert await client.run(args) == 0
        profiles = await client.rpc("providers.list")
        profile = profiles[0]
        assert profile["model"] == "openai/custom"
        assert profile["api_base"] == "http://localhost:1234/v1"
        assert profile["api_key_env"] == "BADSHOP_TEST_KEY"
        assert core.session.data.provider_profile_id == profile["id"]
        assert core.session.data.approval_mode == "ask_all"
        assert f"reuse with --profile {profile['id']}" in client.output.getvalue()

    asyncio.run(run())


def test_terminal_bad_request_reports_error_and_continues(private_env):
    output = io.StringIO()

    async def run():
        core = app()
        client = TerminalClient(core, read=reader(["/save", "/quit"]), output=output)
        assert await client.run(build_parser().parse_args(["chat"])) == 0

    asyncio.run(run())
    assert "no project file yet" in output.getvalue() and "hint:" in output.getvalue()


@pytest.mark.parametrize("command", ["/import", "/open", "/save"])
@pytest.mark.parametrize("path", ["~nosuchuser_badshop/image.png", "bad\0path"])
def test_terminal_invalid_path_reports_error_and_continues(private_env, command, path):
    output = io.StringIO()

    async def run():
        core = app()
        client = TerminalClient(core, read=reader([f"{command} {path}", "/quit"]), output=output)
        assert await client.run(build_parser().parse_args(["chat"])) == 0
        assert core._closed

    asyncio.run(run())
    assert "can't resolve that path" in output.getvalue()
    assert "hint:" in output.getvalue()


@pytest.mark.parametrize("path", ["~nosuchuser_badshop/image.png", "bad\0path"])
def test_terminal_invalid_startup_image_closes_cleanly(private_env, path):
    async def run():
        core = app()
        client = TerminalClient(core, read=reader([]), output=io.StringIO())
        with pytest.raises(EngineError, match="can't resolve"):
            await client.run(build_parser().parse_args(["chat", "--image", path]))
        assert core._closed

    asyncio.run(run())


def test_terminal_symlink_loop_is_a_clean_error(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    try:
        first.symlink_to(second)
        second.symlink_to(first)
    except OSError:
        pytest.skip("symlinks are not available")
    with pytest.raises(EngineError, match="can't resolve"):
        user_path(str(first))


def test_terminal_no_provider_reports_error_and_keeps_imports(private_env):
    photo = private_env / "image.png"
    Image.new("RGB", (8, 8), "red").save(photo)
    output = io.StringIO()

    async def run():
        core = app()
        client = TerminalClient(core, read=reader(["hello", "/quit"]), output=output)
        args = build_parser().parse_args(["chat", "--image", str(photo)])
        assert await client.run(args) == 0
        assert len(client.attachments) == 1
        assert core.session.data.messages == []

    asyncio.run(run())
    assert "no model provider" in output.getvalue()


def test_terminal_attaches_all_imports_to_next_message(private_env):
    photos = [private_env / f"{color}.png" for color in ("red", "blue")]
    for path, color in zip(photos, ("red", "blue")):
        Image.new("RGB", (8, 8), color).save(path)

    async def run():
        core = app()
        core._provider = ScriptedProvider([Reply(text="I see both."), Reply(text="Next.")])
        client = TerminalClient(core, read=reader([f"/import {photos[1]}", "compare", "next", "/quit"]),
                                output=io.StringIO())
        args = build_parser().parse_args(["chat", "--image", str(photos[0])])
        assert await client.run(args) == 0
        messages = [m for m in core.session.data.messages if m.role == "user"]
        assert len([p for p in messages[0].content if p.artifact_id]) == 2
        assert len([p for p in messages[1].content if p.artifact_id]) == 0
        assert client.attachments == []

    asyncio.run(run())


def test_terminal_restore_open_keep_saved_profile_and_clear_attachments(private_env):
    photo = private_env / "image.png"
    Image.new("RGB", (8, 8), "red").save(photo)
    saved = private_env / "restored.badshop"

    async def run():
        first = app()
        client = TerminalClient(first, read=reader(["/quit"]), output=io.StringIO())
        await client.run(build_parser().parse_args(["chat", "--model", "openai/custom"]))
        profile_id = first.session.data.provider_profile_id
        second = app()
        client = TerminalClient(second, output=io.StringIO())
        try:
            await client.import_image(str(photo))
            assert client.attachments
            await client.command("/restore")
            assert client.attachments == []
            assert second.session.data.provider_profile_id == profile_id
            await client.command(f"/save {saved}")
            await client.import_image(str(photo))
            await client.command(f"/open {saved}")
            assert second.session.data.provider_profile_id == profile_id
            assert client.attachments == []
        finally:
            await second.close()

    asyncio.run(run())


@pytest.mark.skipif(os.name == "nt", reason="Windows console Ctrl-C is not subprocess SIGINT")
@pytest.mark.parametrize("attempt", range(3))
@pytest.mark.parametrize("stage", ["initial", "approval"])
def test_terminal_sigint_while_input_waits_exits(private_env, monkeypatch, attempt, stage):
    script = private_env / "script.json"
    script.write_text(json.dumps([{"tool_calls": [{"name": "fetch", "arguments": {
        "query": "never fetched"}}]}]))
    monkeypatch.setenv("BADSHOP_FAKE_PROVIDER", str(script))
    with subprocess.Popen([sys.executable, "-m", "badshop", "chat"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        ready = threading.Event()
        chunks, errors = [], []

        def read():
            while char := proc.stdout.read(1):
                chunks.append(char)
                if ("Approve [y]" if stage == "approval" else "badshop> ") in "".join(chunks):
                    ready.set()

        def drain_errors():
            errors.append(proc.stderr.read())

        worker = threading.Thread(target=read)
        error_worker = threading.Thread(target=drain_errors)
        worker.start()
        error_worker.start()
        try:
            if stage == "approval":
                proc.stdin.write("do it\n")
                proc.stdin.flush()
            assert ready.wait(10), "terminal did not display its input prompt"
            # Ensure cancellation also covers a reader already blocked inside stdin,
            # rather than only the small interval between displaying and reading a prompt.
            time.sleep(.02)
            proc.send_signal(signal.SIGINT)
            code = proc.wait(timeout=5)
            worker.join(timeout=5)
            error_worker.join(timeout=5)
            assert not worker.is_alive() and not error_worker.is_alive()
            stderr = "".join(errors)
            assert code == 130, stderr
            assert "Traceback" not in stderr and "Fatal Python error" not in stderr, stderr
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            worker.join(timeout=5)
            error_worker.join(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="POSIX fd readiness cancellation contract")
def test_cancelled_terminal_input_removes_reader_without_waiting_for_stdin(monkeypatch):
    from badshop.cli.chat import read_input
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stream)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    async def run():
        task = asyncio.create_task(read_input("prompt> "))
        await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not any(t.name == "badshop-input" and t.is_alive() for t in threading.enumerate())
    try:
        asyncio.run(run())
    finally:
        os.close(write_fd)
        for thread in threading.enumerate():
            if thread.name == "badshop-input":
                thread.join(timeout=1)
        stream.close()


@pytest.mark.parametrize("regular_file", [False, True])
def test_terminal_raw_input_preserves_unicode_crlf_and_eof(private_env, regular_file):
    script = '''import asyncio,json
from badshop.cli.chat import read_input
async def main():
    lines=[await read_input("") for _ in range(3)]
    try: await read_input("")
    except EOFError: pass
    else: raise AssertionError("missing EOF")
    print(json.dumps(lines,ensure_ascii=True))
asyncio.run(main())
'''
    content = "雪🙂\r\ncafé\nlast line"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if regular_file:
        path = private_env / "input.txt"
        path.write_bytes(content.encode("utf-8"))
        with path.open("rb") as stream:
            result = subprocess.run([sys.executable, "-c", script], stdin=stream,
                                    capture_output=True, text=True, encoding="utf-8", timeout=5, env=env)
    else:
        result = subprocess.run([sys.executable, "-c", script], input=content,
                                capture_output=True, text=True, encoding="utf-8", timeout=5, env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["雪🙂", "café", "last line"]
    assert "Fatal Python error" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX canonical TTY input")
def test_terminal_tty_keeps_unicode_and_native_line_editing(private_env):
    import pty
    master, slave = pty.openpty()
    script = '''import asyncio,json
from badshop.cli.chat import read_input
print(json.dumps(asyncio.run(read_input("")),ensure_ascii=True))
'''
    try:
        with subprocess.Popen([sys.executable, "-c", script], stdin=slave,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"}) as proc:
            os.close(slave)
            slave = None
            # Canonical terminal editing removes the final ASCII x before the app sees it.
            os.write(master, "café🙂x\x7f\n".encode("utf-8"))
            stdout, stderr = proc.communicate(timeout=5)
            assert proc.returncode == 0, stderr.decode("utf-8", "replace")
            assert json.loads(stdout) == "café🙂"
    finally:
        os.close(master)
        if slave is not None:
            os.close(slave)


def test_windows_raw_console_adapter_keeps_wide_unicode():
    from types import SimpleNamespace
    from badshop.cli.chat import _raw_line
    class _WindowsConsoleIO:
        def __init__(self):
            self.characters = iter("雪🙂\r\n")
        def read(self, size):
            assert size >= 4  # CPython's UTF-8 console adapter needs space for a full codepoint.
            return next(self.characters).encode("utf-8")
    stream = SimpleNamespace(encoding="utf-8", errors="strict",
                             buffer=SimpleNamespace(raw=_WindowsConsoleIO()))
    assert _raw_line(stream) == "雪🙂"
