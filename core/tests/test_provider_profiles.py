"""Profile persistence, secret isolation, server selection and failed-turn retry."""

import asyncio
import json

import pytest

from badshop.agent.fake import ScriptedProvider
from badshop.agent.provider import ProviderError, Reply, ToolCallRequest
from badshop.engine.errors import EngineError
from badshop.providers import profiles
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.session.execution import InProcessExecutor
from badshop.tools import REGISTRY, registry, runner
from test_server_app import LINCOLN
from test_server_app import env as env


def sample(**kw):
    return {"id": "local", "label": "Local vision", "model": "openai/local-vision",
            "kind": "openai_compatible", "api_base": "http://localhost:1234/v1",
            "capability_overrides": {"vision": True, "tool_calls": True}, **kw}


class Keychain:
    def __init__(self):
        self.values = {}

    def get_password(self, service, name):
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        self.values[service, name] = value

    def delete_password(self, service, name):
        self.values.pop((service, name), None)


def test_profiles_validate_and_roundtrip(env):
    p = profiles.parse_profile(sample())
    profiles.save_profiles({p.id: p})
    assert profiles.load_profiles() == {p.id: p}
    for bad in ({"api_key": "never echo this"}, {"api_base": "https://user:secret@example.com"},
                {"api_base": "https://example.com?key=secret"}, {"api_base": "file:///tmp/x"},
                {"api_key_env": "bad-name"}, {"capability_overrides": {"unknown": True}}):
        with pytest.raises(EngineError) as e:
            profiles.parse_profile(sample(**bad))
        assert "secret" not in str(e.value) and "never echo" not in str(e.value)
    profiles.profiles_path().write_text("invalid")
    with pytest.raises(EngineError, match="can't read"):
        profiles.load_profiles()


def test_env_and_keychain_never_fallback_silently(env, monkeypatch):
    monkeypatch.setattr(profiles, "_keyring", lambda: Keychain())
    monkeypatch.setenv("TEST_BADSHOP_KEY", "test-secret")
    assert profiles.resolve_key(profiles.Profile(**sample(api_key_env="TEST_BADSHOP_KEY"))) == "test-secret"
    with pytest.raises(EngineError, match="not set"):
        profiles.resolve_key(profiles.Profile(**sample(api_key_env="MISSING_BADSHOP_KEY")))
    with pytest.raises(EngineError, match="missing"):
        profiles.resolve_key(profiles.Profile(**sample(api_key_ref="local")))

    def fail():
        raise RuntimeError("private backend details")
    monkeypatch.setattr(profiles, "_keyring", fail)
    with pytest.raises(EngineError, match="keychain") as e:
        profiles.store_key("local", "secret")
    assert "private" not in str(e.value)
    assert "api_key_env" in e.value.hint
    assert not profiles.profiles_path().exists()


def test_profile_rpc_secret_isolation_and_permissions(env, monkeypatch):
    keychain = Keychain()
    monkeypatch.setattr(profiles, "_keyring", lambda: keychain)

    async def scenario():
        app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
        try:
            raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "providers.save",
                              "params": {"profile": sample(), "api_key": "private-key"}})
            denied = json.loads(await app.dispatcher.handle(raw, "cli:claude"))
            assert denied["error"]["code"] == -32001
            saved = json.loads(await app.dispatcher.handle(raw, "user"))["result"]
            assert saved["api_key_ref"].startswith("local:")
            assert profiles.resolve_key(profiles.Profile(**saved)) == "private-key"
            assert "private-key" not in profiles.profiles_path().read_text()
            await app._providers_select("user", "local")
            assert app.session.data.provider_profile_id == "local"
            assert "private-key" not in json.dumps(app._snapshot())
            assert "private-key" not in json.dumps(await app._providers_list("user"))
            assert profiles.load_profiles()["local"].model == "openai/local-vision"
            await app._providers_delete("user", "local")
            assert app.session.data.provider_profile_id is None
            assert not keychain.values
        finally:
            await app.close()
    asyncio.run(scenario())


def test_selected_provider_turn_retry_keeps_completed_steps(env, monkeypatch):
    async def scenario():
        app = CoreApp(Settings(approval_mode="auto"), executor_factory=lambda **_: InProcessExecutor())
        try:
            im = app.session.import_image(LINCOLN, "lincoln")
            fake = ScriptedProvider([
                Reply(tool_calls=[ToolCallRequest("call1", "info", {"image": im.id})]),
                ProviderError("temporarily unavailable"), Reply(text="Finished")])
            made = []

            def make(p):
                made.append(p.id)
                return fake
            monkeypatch.setattr(app, "_make_provider", make)
            await app._providers_save("user", sample())
            await app._providers_select("user", "local")
            await app._chat_send("user", "Describe this")
            await app._turn
            assert app._retry_session is app.session
            steps = len(app.session.data.steps)
            users = len([m for m in app.session.data.messages if m.role == "user"])
            await app._chat_retry("user")
            await app._turn
            assert len(app.session.data.steps) == steps == 1
            assert len([m for m in app.session.data.messages if m.role == "user"]) == users == 1
            assert made == ["local", "local"]
            with pytest.raises(EngineError, match="no failed"):
                await app._chat_retry("user")
            assert "data:image" not in json.dumps(app.session.data.transcript)
        finally:
            await app.close()
    asyncio.run(scenario())


def test_font_schema_and_actor_restrictions(monkeypatch):
    from badshop.tools import fonts
    monkeypatch.setattr(fonts, "font_names", lambda: ["Example.ttf"])
    schema = registry.llm_schema(REGISTRY["text"])
    assert schema["properties"]["font"]["anyOf"][0]["enum"] == ["Example.ttf"]
    raw = {"image": "abcd1234", "text": "hello", "font": "/tmp/private.ttf"}
    with pytest.raises(EngineError, match="discovered font"):
        runner.validate("text", raw, "agent:local")
    assert runner.validate("text", raw, "user").font == "/tmp/private.ttf"
    assert runner.validate("text", {**raw, "font": "Example.ttf"}, "cli:claude").font == "Example.ttf"


def test_failed_profile_write_preserves_previous_key(env, monkeypatch):
    keychain = Keychain()
    monkeypatch.setattr(profiles, "_keyring", lambda: keychain)

    async def scenario():
        app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
        try:
            await app._providers_save("user", sample(), "original")
            saved = profiles.profiles_path().read_bytes()
            previous = dict(keychain.values)

            def fail(_):
                raise EngineError("disk full")
            monkeypatch.setattr(profiles, "save_profiles", fail)
            with pytest.raises(EngineError, match="disk full"):
                await app._providers_save("user", sample(), "replacement")
            assert keychain.values == previous
            assert profiles.profiles_path().read_bytes() == saved
            assert profiles.resolve_key(app._profile("local")) == "original"
            with pytest.raises(EngineError, match="disk full"):
                await app._providers_delete("user", "local")
            assert keychain.values == previous
            assert profiles.resolve_key(app._profile("local")) == "original"
        finally:
            await app.close()
    asyncio.run(scenario())


def test_corrupt_profiles_do_not_prevent_session_access_or_get_overwritten(env):
    profiles.profiles_path().parent.mkdir(parents=True)
    profiles.profiles_path().write_text("broken")

    async def scenario():
        app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
        try:
            assert (await app._session_get("user"))["name"] == "Untitled"
            with pytest.raises(EngineError, match="can't read"):
                await app._providers_save("user", sample())
            assert profiles.profiles_path().read_text() == "broken"
        finally:
            await app.close()
    asyncio.run(scenario())


def test_provider_test_is_offline_unless_probe_requested(env, monkeypatch):
    class ProbeProvider:
        calls = 0

        def check_capabilities(self):
            return {"vision": True, "tool_calls": True}

        async def complete(self, messages, tools, on_delta):
            self.calls += 1
            return Reply(text="OK")

    async def scenario():
        app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
        probe = ProbeProvider()
        monkeypatch.setattr(app, "_make_provider", lambda _: probe)
        try:
            await app._providers_save("user", sample())
            result = await app._providers_test("user", "local")
            assert result["status"] == "ready" and result["probed"] is False
            assert probe.calls == 0
            assert (await app._providers_test("user", "local", probe=True))["probed"] is True
            assert probe.calls == 1
            assert (await app._providers_test("user", "missing"))["status"] == "error"
        finally:
            await app.close()
    asyncio.run(scenario())
