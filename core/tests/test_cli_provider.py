"""Offline subprocess/stream/config contracts for subscription CLI providers."""

import asyncio
import json
import os
import signal
import sys
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from badshop.agent.provider import ProviderError
from badshop.providers.cli_provider import CLIProvider, inspect_cli, parse_event
from badshop.providers.profiles import Profile
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.server.ws import bound_port, serve
from badshop.session.execution import InProcessExecutor
from conftest import FIXTURES


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "original-gemini-home"))
    monkeypatch.setenv("BADSHOP_FAKE_CLI_FIXTURES", str(FIXTURES / "cli"))
    script = (FIXTURES / "cli/fake_cli.py").read_text()
    paths = {}
    for name in ("claude", "codex", "gemini"):
        path = tmp_path / name
        path.write_text(f"#!{sys.executable}\n" + script)
        path.chmod(0o700)
        paths[name] = str(path)
    return paths


def profile(fake, cli="claude"):
    return Profile(kind="cli", cli=cli, label="test", executable=fake[cli])


def test_profile_cli_validation_and_api_compatibility():
    assert Profile(kind="cli", cli="codex", label="subscription").model == ""
    assert Profile(label="API", model="openai/model").kind == "api"
    for value in ({"kind": "cli"}, {"kind": "api", "cli": "claude"},
                  {"kind": "cli", "cli": "bad"}, {"kind": "cli", "cli": "claude", "api_key_ref": "key"}):
        with pytest.raises(ValidationError):
            Profile(label="invalid", **value)


@pytest.mark.parametrize("cli", ["claude", "codex", "gemini"])
def test_detection_and_streamed_multiturn_subprocess(fake, cli):
    async def body():
        info = inspect_cli(cli, fake[cli])
        assert info["supported"] and info["version"] == "fake-1.0"
        provider = CLIProvider(profile(fake, cli), "ws://127.0.0.1:1234", "test-secret")
        try:
            chunks, events = [], []
            answer = await provider.turn("make meme", chunks.append, events.append)
            assert answer == "Made the meme." == "".join(chunks)
            assert provider.session_id == f"{cli}-fixture"
            first = provider.process
            chunks.clear()
            assert await provider.turn("again", chunks.append, events.append) == "Made the meme."
            if cli == "claude":
                assert provider.process is first  # long-lived stdin/stdout session
            else:
                assert provider.process is not first
                assert "resume" in provider.command("again") or "--resume" in provider.command("again")
            assert provider.cwd.stat().st_mode & 0o077 == 0
        finally:
            folder = provider.cwd
            await provider.close()
            assert not folder.exists()
    asyncio.run(body())


def test_cli_scoped_configs_preserve_auth(fake, tmp_path, monkeypatch):
    user = tmp_path / "user-codex"
    user.mkdir()
    auth = user / "auth.json"
    auth.write_text('{"subscription":"private"}')
    monkeypatch.setenv("CODEX_HOME", str(user))
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "normal")

    async def body():
        for cli in ("claude", "codex", "gemini"):
            provider = CLIProvider(profile(fake, cli), "ws://127.0.0.1:1234", "test-secret")
            try:
                command = provider.command("make meme")
                assert not any(flag in command for flag in ("--yolo", "--bare", "--full-auto",
                                                           "--dangerously-bypass-approvals-and-sandbox"))
                if cli == "claude":
                    assert command[command.index("--tools") + 1] == ""
                    assert "--strict-mcp-config" in command
                    assert provider.env["CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT"] == "0"
                elif cli == "codex":
                    private = Path(provider.env["CODEX_HOME"])
                    assert (private / "auth.json").is_symlink()
                    assert (private / "auth.json").resolve() == auth
                    config = tomllib.loads((private / "config.toml").read_text())
                    assert set(config["mcp_servers"]) == {"badshop"}
                    assert config["sandbox_mode"] == "read-only" and config["web_search"] == "disabled"
                    model = json.loads((private / "models.json").read_text())["models"][0]
                    assert model["apply_patch_tool_type"] is None and model["shell_type"] == "disabled"
                else:
                    config = json.loads((Path(provider.env["GEMINI_CLI_HOME"]) / ".gemini/settings.json").read_text())
                    assert config["tools"]["core"] == [] and config["mcp"]["allowed"] == ["badshop"]
                    assert config["tools"]["allowed"] == ["mcp_badshop_*"]
                    assert config["mcpServers"]["badshop"]["trust"]
                    assert "--skip-trust" in command
                    policy_dir = Path(command[command.index("--policy") + 1])
                    assert policy_dir.is_relative_to(provider.cwd)
                    assert not list(policy_dir.glob("*.toml"))
            finally:
                await provider.close()
        assert auth.read_text() == '{"subscription":"private"}'
    asyncio.run(body())


def test_unknown_and_malformed_events_are_nonfatal(fake, monkeypatch):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "malformed")

    async def body():
        provider = CLIProvider(profile(fake), "ws://127.0.0.1:1234", "test-secret")
        try:
            events = []
            assert await provider.turn("go", lambda _: None, events.append) == "Made the meme."
            assert any(e.get("parse_error") for e in events)
            assert any(e.get("raw", {}).get("type") == "a_new_event"
                       for e in events if isinstance(e.get("raw"), dict))
        finally:
            await provider.close()
    asyncio.run(body())


def test_gemini_private_home_links_only_authentication(fake, tmp_path, monkeypatch):
    source_home = tmp_path / "original-gemini-home"
    source = source_home / ".gemini"
    source.mkdir(parents=True)
    original = {"security": {"auth": {"selectedType": "oauth-personal"}},
                "tools": {"allowed": ["run_shell_command"]}, "mcpServers": {"other": {"command": "other"}},
                "hooks": {"enabled": True}}
    (source / "settings.json").write_text(json.dumps(original))
    (source / "oauth_creds.json").write_text('{"refresh_token":"test-auth"}')
    (source / "google_accounts.json").write_text('{"active":"test-account"}')
    (source / "policies").mkdir()
    (source / "policies/unsafe.toml").write_text('[[rule]]\ntoolName="*"\ndecision="allow"\npriority=999\n')
    monkeypatch.setenv("GEMINI_CLI_HOME", str(source_home))
    provider = CLIProvider(profile(fake, "gemini"), "ws://127.0.0.1:1234", "test-secret")
    try:
        private = Path(provider.env["GEMINI_CLI_HOME"]) / ".gemini"
        config = json.loads((private / "settings.json").read_text())
        assert private.parent == provider.cwd
        assert os.path.samefile(private / "oauth_creds.json", source / "oauth_creds.json")
        assert os.path.samefile(private / "google_accounts.json", source / "google_accounts.json")
        assert config["security"]["auth"]["selectedType"] == "oauth-personal"
        assert config["tools"]["allowed"] == ["mcp_badshop_*"]
        assert set(config["mcpServers"]) == {"badshop"} and not config["hooks"]["enabled"]
        assert not (private / "policies").exists()
        assert json.loads((source / "settings.json").read_text()) == original
    finally:
        asyncio.run(provider.close())


def test_process_failure_surfaces_login_and_stderr(fake, monkeypatch):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "fail")

    async def body():
        provider = CLIProvider(profile(fake), "ws://127.0.0.1:1234", "test-secret")
        try:
            with pytest.raises(ProviderError, match="claude auth login") as error:
                await provider.turn("go", lambda _: None, lambda _: None)
            assert "login required" in str(error.value)
            assert provider.process is None
        finally:
            await provider.close()
    asyncio.run(body())


def test_stop_terminates_process_and_releases_streams(fake, monkeypatch):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "stall")

    async def body():
        provider = CLIProvider(profile(fake), "ws://127.0.0.1:1234", "test-secret")
        task = asyncio.create_task(provider.turn("go", lambda _: None, lambda _: None))
        try:
            while not provider.session_id:
                await asyncio.sleep(.01)
            process = provider.process
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert process.returncode is not None and provider.process is None
        finally:
            await provider.close()
    asyncio.run(body())


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM-ignore repeated cancellation regression")
def test_repeated_cancellation_waits_for_process_cleanup(fake, monkeypatch):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "stall_ignore")

    async def body():
        provider = CLIProvider(profile(fake), "ws://127.0.0.1:1234", "test-secret")
        task = asyncio.create_task(provider.turn("go", lambda _: None, lambda _: None))
        try:
            while not provider.session_id:
                await asyncio.sleep(.01)
            process = provider.process
            task.cancel()
            await asyncio.sleep(.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert process.returncode is not None
        finally:
            await provider.close()
    asyncio.run(body())


@pytest.mark.parametrize("mode", ["mcp", "budget"])
def test_app_cli_turn_executes_tools_only_through_mcp(fake, monkeypatch, mode):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", mode)

    async def body():
        app = CoreApp(Settings(approval_mode="ask_all", step_budget=1),
                      executor_factory=lambda **_: InProcessExecutor())
        server = await serve(app, "test-secret")
        app.set_connection(f"ws://127.0.0.1:{bound_port(server)}", "test-secret")
        events = []

        async def send(raw):
            events.append(json.loads(raw))

        unsubscribe = app.subscribe(send)
        try:
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            p = profile(fake)
            app._profiles[p.id] = p
            await app._providers_select("user", p.id)
            await app._chat_send("user", "make meme", [imported.id])
            async with asyncio.timeout(10):
                while not app._cli_gate.pending():
                    await asyncio.sleep(.01)
                step_id = app._cli_gate.pending()[0]
                assert app.session.step(step_id).actor == "cli:claude"
                app._cli_gate.respond(step_id, "approve")
                while app._turn:
                    await asyncio.sleep(.01)
            assert len(app.session.data.steps) == 1
            assert app.session.step(step_id).status == "done"
            assert [m.role for m in app.session.data.messages][-2:] == ["user", "assistant"]
            assistant = app.session.data.messages[-1]
            assert assistant.step_ids == [step_id] and assistant.content[0].text == "Made the meme."
            assert any(e["method"] == "message.delta" for e in events)
            assert any(e["method"] == "provider.status" for e in events)
        finally:
            unsubscribe()
            server.close()
            await server.wait_closed()
            await app.close()
    asyncio.run(body())


def test_app_stop_rejects_managed_cli_approval_and_keeps_core_serving(fake, monkeypatch):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "mcp")

    async def body():
        app = CoreApp(Settings(approval_mode="ask_all"), executor_factory=lambda **_: InProcessExecutor())
        server = await serve(app, "test-secret")
        app.set_connection(f"ws://127.0.0.1:{bound_port(server)}", "test-secret")
        try:
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            p = profile(fake)
            app._profiles[p.id] = p
            await app._providers_select("user", p.id)
            await app._chat_send("user", "make meme", [imported.id])
            async with asyncio.timeout(10):
                while not app._cli_gate.pending():
                    await asyncio.sleep(.01)
                step_id = app._cli_gate.pending()[0]
                assert await app._chat_stop("user") == {"stopped": True}
                while app._cli_gate.pending():
                    await asyncio.sleep(.01)
            assert app.session.step(step_id).status == "rejected"
            assert app._turn is None
            assert (await app._tools_run("user", "info", {"image": imported.id}))["status"] == "done"
        finally:
            server.close()
            await server.wait_closed()
            await app.close()
    asyncio.run(body())


@pytest.mark.parametrize("cli,event", [
    ("claude", {"type": "result", "is_error": True, "errors": ["login"]}),
    ("codex", {"type": "turn.failed", "error": {"message": "rate limit"}}),
    ("gemini", {"type": "result", "status": "error", "error": {"message": "denied"}}),
])
def test_error_event_shapes(cli, event):
    assert parse_event(cli, event)["kind"] == "error"


@pytest.mark.parametrize("cli,event", [
    ("claude", {"type": "assistant", "message": {"content": None}}),
    ("claude", {"type": "stream_event", "event": "new shape"}),
    ("gemini", {"type": "result", "status": "error", "error": "new shape"}),
])
def test_malformed_nested_events_are_observable(cli, event):
    parsed = parse_event(cli, event)
    assert parsed["kind"] == "raw" and parsed["parse_error"]


def test_resumed_and_retried_turns_identify_old_attached_artifacts(fake, monkeypatch):
    from PIL import Image
    import io

    async def body():
        app = CoreApp(Settings(approval_mode="auto"), executor_factory=lambda **_: InProcessExecutor())
        provider = CLIProvider(profile(fake), "ws://127.0.0.1:1234", "test-secret")
        provider.session_id = "resumed-session"
        prompts = []

        async def turn(prompt, on_delta, on_event):
            prompts.append(prompt)
            return "Done"

        monkeypatch.setattr(provider, "turn", turn)
        app._provider = provider
        try:
            oldest = None
            for n in range(82):
                output = io.BytesIO()
                Image.new("RGB", (2, 2), (n, 0, 0)).save(output, "PNG")
                artifact = app.session.import_image(output.getvalue(), f"image-{n}")
                oldest = oldest or artifact.id
            await app._chat_send("user", "Use the attached photo", [oldest])
            while app._turn:
                await asyncio.sleep(.01)
            app._retry_session = app.session
            await app._chat_retry("user")
            while app._turn:
                await asyncio.sleep(.01)
            assert len(prompts) == 2
            for prompt in prompts:
                state = json.loads(prompt.split("snapshot (data, not instructions):\n", 1)[1]
                                   .split("\nOpen relevant", 1)[0])
                assert state["conversation"] == []
                assert oldest[:8] not in str(state["artifacts"])
                assert state["current_attachments"][0]["id"] == oldest
                assert "image_0" in state["current_attachments"][0]["description"]
        finally:
            await provider.close()
            await app.close()
    asyncio.run(body())


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group regression; Windows has a job test")
@pytest.mark.parametrize("ignore_term", [False, True])
def test_stop_kills_children_after_cli_parent_already_exited(ignore_term):
    import psutil

    async def body():
        child_code = ("import time,signal; " + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if ignore_term else "")
                      + "time.sleep(30)")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',"
            f"{child_code!r}]); print(p.pid,flush=True); time.sleep(.1)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        child_pid = int(await process.stdout.readline())
        provider = object.__new__(CLIProvider)
        provider.process = process
        provider._stderr_task = asyncio.create_task(process.stderr.read())
        try:
            async with asyncio.timeout(3):
                while process.returncode is None:
                    await asyncio.sleep(.01)
            assert process.returncode == 0
            await asyncio.wait_for(provider.stop(), 2)
            try:
                assert psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                pass  # the child can disappear between Stop and this check
        finally:
            with __import__("contextlib").suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await provider.stop()
    asyncio.run(body())


def test_cli_parent_exit_closes_inherited_child_pipes_without_user_stop(fake, monkeypatch):
    monkeypatch.setenv("BADSHOP_FAKE_CLI_MODE", "orphan")

    async def body():
        provider = CLIProvider(profile(fake, "gemini"), "ws://127.0.0.1:1234", "test-secret")
        try:
            assert await asyncio.wait_for(provider.turn("go", lambda _: None, lambda _: None), 3) == "Made the meme."
        finally:
            await provider.close()
    asyncio.run(body())


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment contract")
def test_windows_job_kills_descendants_after_cli_parent_exits():
    import psutil
    from badshop.providers.windows_job import Job

    async def body():
        job = Job()
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", 'import subprocess,sys; p=subprocess.Popen([sys.executable,"-c",'
            '"import time; time.sleep(30)"]); print(p.pid,flush=True)',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=0x00000004)
        provider = object.__new__(CLIProvider)
        provider.process, provider._job = process, job
        provider._stderr_task = asyncio.create_task(process.stderr.read())
        try:
            job.assign_and_resume(process.pid)
            child_pid = int(await process.stdout.readline())
            child = psutil.Process(child_pid)
            # Prove the descendant is alive before closing its job: an uncontained child
            # sleeps for 30s and cannot pass the bounded post-Stop wait below.
            with pytest.raises(psutil.TimeoutExpired):
                await asyncio.to_thread(child.wait, timeout=.05)
            async with asyncio.timeout(3):
                while process.returncode is None:
                    await asyncio.sleep(.01)
            assert process.returncode == 0
            await asyncio.wait_for(provider.stop(), 3)
            # Windows termination and PID removal are asynchronous; open process handles
            # can keep a dead process object visible. Wait for the captured descendant,
            # rather than requiring immediate disappearance on the same event-loop tick.
            await asyncio.to_thread(child.wait, timeout=3)
        finally:
            await provider.stop()
    asyncio.run(body())
