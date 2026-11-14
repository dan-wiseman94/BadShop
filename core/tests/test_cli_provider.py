"""Offline subprocess/stream/config contracts for subscription CLI providers."""

import asyncio
import json
import os
import shutil
import subprocess
import signal
import sys
import tempfile
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
    if os.name == "nt":
        # Windows cannot execute a POSIX shebang. Only adapt the fixture launch;
        # real pipes, process jobs, CLI streams and MCP subprocesses remain in use.
        run, spawn = subprocess.run, asyncio.create_subprocess_exec
        def fixture_command(command):
            return [sys.executable, *command] if command[0] in paths.values() else command
        monkeypatch.setattr(subprocess, "run", lambda command, *a, **kw: run(fixture_command(command), *a, **kw))
        async def launch(*command, **kwargs):
            return await spawn(*fixture_command(command), **kwargs)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
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
            if os.name != "nt":  # Windows privacy is inherited ACLs, not POSIX mode bits.
                assert provider.cwd.stat().st_mode & 0o077 == 0
        finally:
            folder = provider.cwd
            await provider.close()
            assert not folder.exists()
    asyncio.run(body())


def test_profile_edits_retire_persistent_process_and_directory(fake, monkeypatch):
    from badshop.engine.errors import EngineError
    from badshop.providers import profiles

    async def body():
        app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
        app.set_connection("ws://127.0.0.1:1234", "test-secret")
        current = profile(fake)
        try:
            await app._providers_save("user", current.model_dump(mode="json"))
            for index in range(3):
                provider = app._make_provider(current)
                await provider.turn("make meme", lambda _: None, lambda _: None)
                process, folder = provider.process, provider.cwd
                assert process is not None and process.returncode is None and folder.exists()
                current = current.model_copy(update={"label": f"edited {index}"})
                if index == 0:
                    def fail_save(_):
                        raise EngineError("disk full")
                    with monkeypatch.context() as patch:
                        patch.setattr(profiles, "save_profiles", fail_save)
                        with pytest.raises(EngineError, match="disk full"):
                            await app._providers_save("user", current.model_dump(mode="json"))
                    assert process.returncode is None and folder.exists()
                    assert list(app._cli_providers.values()) == [provider]
                await app._providers_save("user", current.model_dump(mode="json"))
                assert process.returncode is not None
                assert not folder.exists()
                assert not app._cli_providers and not app._retired_clis
        finally:
            await app.close()
    asyncio.run(body())


def test_desktop_path_launches_discovered_cli(fake, tmp_path, monkeypatch):
    home = tmp_path / "CLI home 🖼"
    monkeypatch.setattr(Path, "home", lambda: home)
    prompt = 'literal %BADSHOP_CLI_TEST% & "quoted" | text'
    monkeypatch.setenv("BADSHOP_CLI_TEST", "expanded")
    if os.name == "nt":
        node = shutil.which("node.exe")
        assert node, "Node is required for the Windows npm launch regression"
        other = tmp_path / "earlier on PATH"
        other.mkdir()
        (other / "node.exe").write_text("invalid fixture")
        monkeypatch.setenv("PATH", str(other))
        folder = home / "npm"
        monkeypatch.setenv("APPDATA", str(home))
        monkeypatch.setenv("LOCALAPPDATA", str(home))
        package = folder / "node_modules/@google/gemini-cli"
        package.mkdir(parents=True)
        try:
            os.link(node, folder / "node.exe")
        except OSError:
            shutil.copyfile(node, folder / "node.exe")
        (folder / "gemini.cmd").write_text("@exit /b 42\n")
        (package / "package.json").write_text('{"bin":{"gemini":"cli.js"}}')
        (package / "cli.js").write_text(
            'const args = process.argv.slice(2);\n'
            'if (args.includes("--version")) console.log("fake-1.0");\n'
            'else if (args.includes("--help")) console.log("--output-format --resume '
            '--allowed-mcp-server-names --policy --skip-trust");\n'
            'else {\n'
            '  console.log(JSON.stringify({type:"message", role:"assistant", content:args.at(-1)}));\n'
            '  console.log(JSON.stringify({type:"result", status:"success"}));\n'
            '}\n'
        )
    else:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        folder = home / ".local/bin"
        folder.mkdir(parents=True)
        (folder / "badshop-python").symlink_to(sys.executable)
        script = Path(fake["gemini"]).read_text().split("\n", 1)[1]
        (folder / "gemini").write_text("#!/usr/bin/env badshop-python\n" + script)
        (folder / "gemini").chmod(0o700)

    async def body():
        info = inspect_cli("gemini")
        assert info["supported"] and info["version"] == "fake-1.0", info
        # Win32 accepts the pasted trailing space when opening the file.
        executable = f'"{info["executable"]} "' if os.name == "nt" else None
        p = Profile(kind="cli", cli="gemini", label="desktop", executable=executable)
        provider = CLIProvider(p, "ws://127.0.0.1:1234", "test-secret")
        cwd = provider.cwd
        try:
            answer = await provider.turn(prompt, lambda _: None, lambda _: None)
            assert answer == (prompt if os.name == "nt" else "Made the meme.")
        finally:
            await provider.close()
        assert not cwd.exists()

    asyncio.run(body())


def test_cli_scoped_configs_preserve_auth(fake, tmp_path, monkeypatch):
    temp_dir = tmp_path / ("scratch 🖼" if os.name == "nt" else "scratch 🖼\x7f")
    temp_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_dir))
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
                    assert (private / "auth.json").samefile(auth)  # symlink or Windows hard-link fallback
                    assert (private / "auth.json").read_bytes() == auth.read_bytes()
                    config = tomllib.loads((private / "config.toml").read_text(encoding="utf-8"))
                    assert Path(config["model_catalog_json"]) == private / "models.json"
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
                "hooksConfig": {"enabled": True},
                "hooks": {"BeforeTool": [{"hooks": [{"type": "command", "command": "unsafe-hook"}]}]}}
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
        assert set(config["mcpServers"]) == {"badshop"} and not config["hooksConfig"]["enabled"]
        assert "hooks" not in config
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
                    assert app._turn is not None, app.session.data.messages
                    await asyncio.sleep(.01)
                step_id = app._cli_gate.pending()[0]
                assert app.session.step(step_id).actor == app._cli_turn_actor
                assert app.session.step(step_id).actor.startswith('cli:claude:')
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
                    assert app._turn is not None, app.session.data.messages
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


@pytest.mark.parametrize('boundary', ['document', 'branch', 'profile'])
def test_adapter_grant_is_idle_between_runs_reusable_and_revoked_on_replacement(fake, monkeypatch, boundary):
    from badshop.mcp.proxy import CoreConnection, CoreError
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    async def body():
        app = CoreApp(Settings(approval_mode='auto'), executor_factory=lambda **_: InProcessExecutor())
        server = await serve(app, 'grant-test-renderer')
        url = f'ws://127.0.0.1:{bound_port(server)}'
        app.set_connection(url, 'grant-test-renderer')
        p = profile(fake)
        app._profiles[p.id] = p
        await app._providers_select('user', p.id)
        provider = app._make_provider(p)
        grant = app._grants.get(provider.authorization_id)
        proxy = CoreConnection(url, grant.token, 'cli:claude')
        image = app.session.import_image((FIXTURES / 'lincoln.png').read_bytes(), 'lincoln')
        entered, release = asyncio.Event(), asyncio.Event()
        old_socket = None

        async def turn(prompt, on_delta, on_event):
            entered.set()
            await release.wait()
            return 'Done'

        monkeypatch.setattr(provider, 'turn', turn)
        try:
            assert await proxy.call('tools.list')
            with pytest.raises(CoreError, match='no active run'):
                await proxy.call('tools.run', {'tool': 'info', 'params': {'image': image.id}})
            run_ids = []
            for n in range(2):
                entered.clear()
                release.clear()
                await app._chat_send('user', f'turn {n}')
                await asyncio.wait_for(entered.wait(), 2)
                run_ids.append(grant.run_id)
                if n == 0:
                    old_socket = await connect(url)
                    await old_socket.send(json.dumps({'type': 'hello', 'actor': 'cli:claude', 'token': grant.token}))
                    assert json.loads(await old_socket.recv())['type'] == 'welcome'
                    await old_socket.send(json.dumps({'jsonrpc': '2.0', 'id': 'scope', 'method': 'credits.get',
                                                      'params': {'artifact_id': image.id}}))
                    scope_reply = json.loads(await asyncio.wait_for(old_socket.recv(), 2))
                    assert scope_reply['id'] == 'scope'
                    assert scope_reply['error']['message'] == 'This method is outside the CLI grant scope.'
                else:
                    await old_socket.send(json.dumps({'jsonrpc': '2.0', 'id': 'stale-run', 'method': 'tools.run',
                                                      'params': {'tool': 'info', 'params': {'image': image.id}}}))
                    async with asyncio.timeout(2):
                        while True:
                            reply = json.loads(await old_socket.recv())
                            if reply.get('id') == 'stale-run':
                                break
                    assert reply['error']['message'] == 'This CLI connection belongs to another run.'
                result = await proxy.call('tools.run', {'tool': 'info', 'params': {'image': image.id}})
                assert result['status'] == 'done' and result['actor'] == grant.execution_actor
                task = app._turn
                release.set()
                await task
                assert grant.run_id is None and not grant.revoked
                with pytest.raises(CoreError, match='no active run'):
                    await proxy.call('artifacts.get', {'id': image.id})
            assert run_ids[0] != run_ids[1]
            assert app._cli_providers[(app.session.data.id, p.id)] is provider
            if boundary == 'document':
                await app._session_new('user', 'new document')
            elif boundary == 'branch':
                await app._branches_create('user', 'new direction')
            else:
                await app._providers_delete('user', p.id)
            assert grant.revoked and not provider.cwd.exists()
            assert app._grants.get(grant.id) is None
            with pytest.raises(ConnectionClosed):
                await proxy.call('tools.list')
        finally:
            release.set()
            if old_socket:
                await old_socket.close()
            server.close()
            await server.wait_closed()
            await app.close()
    asyncio.run(body())


def test_stop_revokes_a_cli_call_already_queued_for_execution(fake, monkeypatch):
    from badshop.mcp.proxy import CoreConnection, CoreError

    async def body():
        app = CoreApp(Settings(approval_mode='auto'), executor_factory=lambda **_: InProcessExecutor())
        server = await serve(app, 'queued-grant-renderer')
        url = f'ws://127.0.0.1:{bound_port(server)}'
        app.set_connection(url, 'queued-grant-renderer')
        p = profile(fake)
        app._profiles[p.id] = p
        await app._providers_select('user', p.id)
        provider = app._make_provider(p)
        grant = app._grants.get(provider.authorization_id)
        proxy = CoreConnection(url, grant.token, 'cli:claude')
        image = app.session.import_image((FIXTURES / 'lincoln.png').read_bytes(), 'lincoln')
        entered, admitted = asyncio.Event(), asyncio.Event()

        async def turn(prompt, on_delta, on_event):
            entered.set()
            await asyncio.Event().wait()

        authorize = app.authorize_cli
        def observed(grant, method):
            result = authorize(grant, method)
            if method == 'tools.run':
                admitted.set()
            return result

        monkeypatch.setattr(provider, 'turn', turn)
        monkeypatch.setattr(app, 'authorize_cli', observed)
        try:
            await app._chat_send('user', 'run')
            await asyncio.wait_for(entered.wait(), 2)
            async with app._lock:
                queued = asyncio.create_task(proxy.call('tools.run', {'tool': 'info', 'params': {'image': image.id}}))
                await asyncio.wait_for(admitted.wait(), 2)
                stopped = asyncio.create_task(app._chat_stop('user'))
                await asyncio.sleep(0)
                assert grant.run_id is None
            with pytest.raises(CoreError, match='document changed'):
                await queued
            assert await stopped == {'stopped': True}
            assert app.session.data.steps == []
            assert app._cli_gate.pending() == []
        finally:
            server.close()
            await server.wait_closed()
            await app.close()
    asyncio.run(body())


def test_cli_rejection_preserves_budget_and_parallel_approvals_cannot_overspend(fake, monkeypatch):
    from badshop.engine.errors import EngineError

    async def body():
        app = CoreApp(Settings(approval_mode='ask_all', step_budget=1),
                      executor_factory=lambda **_: InProcessExecutor())
        provider = CLIProvider(profile(fake), 'ws://127.0.0.1:1234', 'test-secret')
        app._provider = provider
        image = app.session.import_image((FIXTURES / 'lincoln.png').read_bytes(), 'lincoln')
        results = []

        async def turn(prompt, on_delta, on_event):
            async def propose():
                return await app._tools_run(provider.actor, 'filter', {'image': image.id, 'names': ['invert']})

            rejected = asyncio.create_task(propose())
            while not app._cli_gate.pending():
                await asyncio.sleep(0)
            app._cli_gate.respond(app._cli_gate.pending()[0], 'reject')
            results.append(await rejected)
            first, second = asyncio.create_task(propose()), asyncio.create_task(propose())
            while len(app._cli_gate.pending()) != 2:
                await asyncio.sleep(0)
            for step_id in app._cli_gate.pending():
                app._cli_gate.respond(step_id, 'approve')
            results.extend(await asyncio.gather(first, second))
            with pytest.raises(EngineError, match='budget is used up'):
                await propose()
            return 'Finished'

        monkeypatch.setattr(provider, 'turn', turn)
        try:
            await app._chat_send('user', 'Edit the image', [image.id])
            await asyncio.wait_for(app._turn, 10)
            assert [result['status'] for result in results] == ['rejected', 'done', 'rejected']
            output = app.session.artifacts.image(results[1]['outputs'][0])
            original = app.session.artifacts.image(image.id)
            assert output.getpixel((0, 0)) == tuple(255 - c for c in original.convert('RGB').getpixel((0, 0)))
            assert app._cli_gate.pending() == []
            assert app._snapshot()['last_turn_outcome']['reason'] == 'budget'
        finally:
            await provider.close()
            await app.close()
    asyncio.run(body())


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
            # SIGKILL closes inherited pipes before the kernel necessarily publishes
            # the final process state. Require termination within a bounded deadline,
            # not on the exact event-loop tick that observes pipe EOF.
            async with asyncio.timeout(1):
                while True:
                    try:
                        if psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE:
                            break
                    except psutil.NoSuchProcess:
                        break
                    await asyncio.sleep(.01)
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
