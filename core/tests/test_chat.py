"""The terminal uses the real dispatcher, session and approval loop, without a paid provider."""

import asyncio
import io
import json
import os
import signal
import subprocess
import sys
import threading

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
def test_terminal_sigint_while_input_waits_exits(private_env, monkeypatch):
    script = private_env / "script.json"
    script.write_text(json.dumps([{"tool_calls": [{"name": "fetch", "arguments": {
        "query": "never fetched"}}]}]))
    monkeypatch.setenv("BADSHOP_FAKE_PROVIDER", str(script))
    with subprocess.Popen([sys.executable, "-m", "badshop", "chat"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        ready = threading.Event()
        chunks = []

        def read():
            while char := proc.stdout.read(1):
                chunks.append(char)
                if "Approve [y]" in "".join(chunks):
                    ready.set()

        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        try:
            proc.stdin.write("do it\n")
            proc.stdin.flush()
            assert ready.wait(10), "terminal did not ask for approval"
            proc.send_signal(signal.SIGINT)
            assert proc.wait(timeout=5) == 130
            worker.join(timeout=5)
            assert not worker.is_alive()
            assert "Traceback" not in proc.stderr.read()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            worker.join(timeout=5)
