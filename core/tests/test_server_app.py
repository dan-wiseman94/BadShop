"""Server core (Task 12): settings, the JSON-RPC dispatcher, and CoreApp's methods and events.

No sockets: a `Client` here does what one WebSocket connection does in server/ws.py (Task 13), it
subscribes to events and sends JSON-RPC frames through `app.dispatcher.handle`. Tools run through
InProcessExecutor (the worker has its own tests), and only tools that need no download are used."""

import asyncio
import base64
import io
import json
import threading
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine import assets, manifest
from badshop.engine.errors import EngineError
from badshop.server import app as server_app
from badshop.server import rpc
from badshop.server.app import CoreApp
from badshop.server.rpc import Dispatcher, RpcError
from badshop.server.settings import Settings, config_dir, load_settings, save_settings, settings_path
from badshop.session import project
from badshop.session.execution import InProcessExecutor, ToolOutcome
from badshop.session.session import Session
from conftest import FIXTURES

LINCOLN = (FIXTURES / "lincoln.png").read_bytes()
TRUMP = FIXTURES / "trump.png"
HEAD = [100, 50, 350, 330]  # a box on lincoln's 457x600 working copy
NO_HOME = "~nosuchuser_badshop"  # "~name" for a user this computer doesn't have: pathlib can't expand it
METHODS = sorted([
    "session.new", "session.get", "session.open", "session.restore", "session.save", "session.save_as",
    "session.export_recipe", "session.set_approval_mode", "chat.send", "chat.stop", "tools.list",
    "tools.run", "steps.edit", "steps.replay_from", "steps.delete", "approval.respond", "artifacts.get",
    "artifacts.import", "export", "settings.get", "settings.set", "assets.status", "assets.download",
])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Private config, data (autosave) and output folders for one test."""
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "out"))
    monkeypatch.delenv("BADSHOP_FAKE_PROVIDER", raising=False)
    return tmp_path


# --- settings -----------------------------------------------------------------------------------


def test_settings_round_trip_and_bad_files(env):
    assert config_dir() == env / "config"
    assert load_settings() == Settings()  # no file yet
    s = Settings(approval_mode="auto", step_budget=7, output_dir=str(env / "pics"))
    save_settings(s)
    assert load_settings() == s
    assert [p.name for p in config_dir().iterdir()] == ["settings.json"]  # the temp file was renamed away
    settings_path().write_text("{not json", encoding="utf-8")
    assert load_settings() == Settings()
    settings_path().write_text("[1, 2]", encoding="utf-8")
    assert load_settings() == Settings()
    # a value that is no longer valid, and a key from a newer version, are dropped; the rest is kept
    settings_path().write_text(json.dumps({"step_budget": 0, "auto_replay": False, "from_the_future": 1}),
                               encoding="utf-8")
    assert load_settings() == Settings(auto_replay=False)


def test_settings_bounds():
    assert Settings().model_dump() == {
        "approval_mode": "ask_changes", "auto_replay": True, "output_dir": None, "step_budget": 40,
        "tool_timeout_s": 120.0, "tool_memory_mb": 3072, "fake_provider_script": None}
    for bad in ({"step_budget": 0}, {"step_budget": 501}, {"tool_timeout_s": 0.5}, {"tool_timeout_s": 3601},
                {"tool_timeout_s": float("inf")}, {"tool_memory_mb": 255}, {"tool_memory_mb": 65537},
                {"approval_mode": "yolo"}, {"output_dir": "relative/folder"},
                {"output_dir": f"{NO_HOME}/pics"}, {"nope": 1}):
        with pytest.raises(ValidationError):
            Settings(**bad)


def test_settings_files_that_would_break_loading(env):
    """load_settings never raises: a home folder that doesn't exist is an invalid value (dropped, the rest
    kept), and a file nested too deeply for json is unreadable (the defaults)."""
    config_dir().mkdir(parents=True)
    no_home = json.dumps({"output_dir": f"{NO_HOME}/pics", "step_budget": 7})
    settings_path().write_text(no_home, encoding="utf-8")
    assert load_settings() == Settings(step_budget=7)
    for deep in ("[" * 100_000, '{"step_budget": ' + "[" * 100_000):
        settings_path().write_text(deep, encoding="utf-8")
        assert load_settings() == Settings()


# --- the dispatcher -----------------------------------------------------------------------------


def _dispatcher() -> Dispatcher:
    d = Dispatcher()

    @d.method("echo", actors="any")
    async def echo(actor: str, text: str, times: int = 1) -> dict:
        return {"actor": actor, "text": text * times}

    @d.method("secret")
    async def secret(actor: str) -> str:
        return "for the user only"

    @d.method("engine")
    async def engine(actor: str) -> None:
        raise EngineError("no such artifact: abc123", hint="use an artifact id")

    @d.method("custom")
    async def custom(actor: str) -> None:
        raise RpcError(rpc.INVALID_PARAMS, "give either path or data")

    @d.method("bug")
    async def bug(actor: str) -> None:
        raise ZeroDivisionError("oops")

    @d.method("unencodable")
    async def unencodable(actor: str) -> object:
        return object()

    return d


def _ask(d: Dispatcher, msg, actor: str = "user") -> dict | None:
    reply = asyncio.run(d.handle(msg if isinstance(msg, str) else json.dumps(msg), actor))
    return None if reply is None else json.loads(reply)


def _req(method: str, params=None, id=1) -> dict:
    msg = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def test_dispatcher_results():
    d = _dispatcher()
    assert _ask(d, _req("echo", {"text": "ab", "times": 2}, id="x")) == {
        "jsonrpc": "2.0", "id": "x", "result": {"actor": "user", "text": "abab"}}
    assert _ask(d, _req("echo", {"text": "hi"}), "cli:claude")["result"] == {"actor": "cli:claude",
                                                                           "text": "hi"}
    assert _ask(d, _req("secret"))["result"] == "for the user only"  # params may be left out
    # a notification (no id) runs but gets no reply, even when it fails
    assert _ask(d, {"jsonrpc": "2.0", "method": "echo", "params": {"text": "x"}}) is None
    assert _ask(d, {"jsonrpc": "2.0", "method": "engine"}) is None
    with pytest.raises(ValueError):
        d.method("echo")  # registering a name twice
    with pytest.raises(ValueError):
        d.method("other", actors="agents")


def test_dispatcher_errors():
    d = _dispatcher()

    def error(msg, actor="user") -> dict:
        reply = _ask(d, msg, actor)
        assert set(reply) == {"jsonrpc", "id", "error"}
        return reply["error"] | {"id": reply["id"]}

    assert error("{nope")["code"] == rpc.PARSE_ERROR
    assert error("{nope")["id"] is None
    # nesting deeper than json's scanner goes raises RecursionError, not ValueError: still a parse error
    for deep in ("[" * 100_000, "[" * 100_000 + "]" * 100_000):
        assert error(deep) == {"code": rpc.PARSE_ERROR, "id": None,
                               "message": "parse error: the JSON is nested too deeply"}
    assert error("[]")["code"] == rpc.INVALID_REQUEST  # batches are refused
    assert error({"jsonrpc": "2.0", "id": [1], "method": "echo"})["code"] == rpc.INVALID_REQUEST
    assert error({"id": 3, "method": "echo"}) == {
        "code": rpc.INVALID_REQUEST, "message": "invalid request", "id": 3,
        "data": {"hint": 'a request needs "jsonrpc": "2.0" and a "method" string'}}
    assert error({"jsonrpc": "2.0", "id": 4, "method": 7})["code"] == rpc.INVALID_REQUEST
    assert error(_req("nope"))["code"] == rpc.METHOD_NOT_FOUND
    forbidden = error(_req("secret"), "cli:claude")
    assert forbidden["code"] == rpc.FORBIDDEN and forbidden["message"] == "cli:claude may not call secret"
    for params in ({}, {"text": 5}, {"text": "a", "bogus": 1}, {"text": "a", "actor": "user"}, ["a"]):
        e = error(_req("echo", params))
        assert e["code"] == rpc.INVALID_PARAMS, params
    assert "text" in error(_req("echo", {}))["data"]["hint"]  # says which parameter is wrong
    assert error(_req("engine")) == {"code": rpc.ENGINE_ERROR, "message": "no such artifact: abc123",
                                     "data": {"hint": "use an artifact id"}, "id": 1}
    assert error(_req("custom")) == {"code": rpc.INVALID_PARAMS, "message": "give either path or data",
                                     "id": 1}
    bug = error(_req("bug"))
    assert bug["code"] == rpc.INTERNAL_ERROR and "ZeroDivisionError: oops" in bug["message"]
    assert error(_req("unencodable"))["code"] == rpc.INTERNAL_ERROR


def test_notification_frame():
    assert json.loads(rpc.notification("turn.finished", {"reason": "done"})) == {
        "jsonrpc": "2.0", "method": "turn.finished", "params": {"reason": "done"}}


# --- CoreApp ------------------------------------------------------------------------------------


class Failed(Exception):
    def __init__(self, error: dict):
        super().__init__(error["message"])
        self.code, self.message, self.data = error["code"], error["message"], error.get("data")


class Client:
    """One connection's view of the app: events in, JSON-RPC calls out."""

    def __init__(self, app: CoreApp, actor: str = "user"):
        self.app, self.actor, self.events, self._ids = app, actor, [], 0
        self._cond = asyncio.Condition()
        self.unsubscribe = app.subscribe(self._on_event)

    async def _on_event(self, msg: str) -> None:
        async with self._cond:
            self.events.append(json.loads(msg))
            self._cond.notify_all()

    async def call(self, method: str, **params):
        self._ids += 1
        id_ = self._ids  # calls may overlap: each one checks its own id
        frame = json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
        reply = json.loads(await self.app.dispatcher.handle(frame, self.actor))
        assert reply["id"] == id_
        if "error" in reply:
            raise Failed(reply["error"])
        return reply["result"]

    async def event(self, method: str, match=lambda params: True, timeout: float = 10.0) -> dict:
        """The params of the first `method` event that `match`es, waiting for it if it hasn't come yet."""
        def found():
            hits = (e["params"] for e in self.events if e["method"] == method and match(e["params"]))
            return next(hits, None)

        async with self._cond:
            await asyncio.wait_for(self._cond.wait_for(lambda: found() is not None), timeout)
            return found()

    async def waiting(self, match=lambda step: True) -> str:
        """The id of the first step announced by approval.needed that `match`es."""
        return (await self.event("approval.needed", lambda p: match(p["step"])))["step"]["id"]

    async def count(self, method: str, n: int, timeout: float = 10.0) -> None:
        """Wait until `method` has arrived n times."""
        async with self._cond:
            await asyncio.wait_for(self._cond.wait_for(lambda: self.methods().count(method) >= n), timeout)

    def methods(self) -> list[str]:
        return [e["method"] for e in self.events]


def in_process(**limits) -> InProcessExecutor:
    return InProcessExecutor()


def run(body, settings: Settings | None = None, factory=in_process):
    async def main():
        app = CoreApp(settings or Settings(), executor_factory=factory)
        try:
            return await asyncio.wait_for(body(app), 60)
        finally:
            await app.close()

    return asyncio.run(main())


async def imported(c: Client, data: bytes = LINCOLN, name: str = "lincoln.png") -> str:
    r = await c.call("artifacts.import", data=base64.b64encode(data).decode(), name=name)
    return r["working"]["id"]


async def idle(c: Client) -> dict:
    """The snapshot once no turn is running (a stopped turn finishes its cleanup after its last event)."""
    for _ in range(500):
        snap = await c.call("session.get")
        if not snap["turn_running"]:
            return snap
        await asyncio.sleep(0.01)
    raise AssertionError("the turn never ended")


def script(env: Path, replies: list[dict]) -> str:
    path = env / "script.json"
    path.write_text(json.dumps(replies), encoding="utf-8")
    return str(path)


def test_methods_are_the_protocol(env):
    async def body(app):
        assert app.dispatcher.names() == METHODS

    run(body)


def test_import_run_get_and_events(env, monkeypatch):
    async def body(app):
        c = Client(app)
        trump = await c.call("artifacts.import", path=str(TRUMP))
        # a small upright PNG is its own working copy, stored once; the label is the file name's stem + _work
        assert trump["working"] == trump["original"] and trump["working"]["label"] == "trump_work"
        assert trump["original"]["width"] == 474
        buf = io.BytesIO()
        with Image.open(TRUMP) as im:
            im.convert("RGB").save(buf, "JPEG")
        photo = await c.call("artifacts.import", data=base64.b64encode(buf.getvalue()).decode(), name="photo.jpg")
        assert (photo["working"]["label"], photo["original"]["label"]) == ("photo_work", "photo")
        assert (photo["working"]["format"], photo["original"]["format"]) == ("PNG", "JPEG")
        assert photo["working"]["original_id"] == photo["original"]["id"]
        for missing in (env / "nope.png", env):  # a missing file, a folder: clean errors
            with pytest.raises(Failed) as e:
                await c.call("artifacts.import", path=str(missing))
            assert e.value.code == rpc.ENGINE_ERROR and e.value.message.startswith("can't read")
        with monkeypatch.context() as m, pytest.raises(Failed) as e:  # refused before it is read
            m.setattr(server_app, "MAX_IMPORT_BYTES", 1000)
            await c.call("artifacts.import", path=str(TRUMP))
        assert e.value.message == "trump.png is too big to import"
        with pytest.raises(Failed) as e:
            await c.call("artifacts.import", path="trump.png")
        assert "absolute" in e.value.message
        with pytest.raises(Failed) as e:
            await c.call("artifacts.import", path=str(TRUMP), data="AAAA")
        assert e.value.code == rpc.INVALID_PARAMS
        with pytest.raises(Failed) as e:
            await c.call("artifacts.import", data="not base64!")
        assert e.value.code == rpc.INVALID_PARAMS
        lincoln = await imported(c)

        step = await c.call("tools.run", tool="cutout",
                            params={"image": lincoln[:8], "box": HEAD, "no_ai": True})
        assert step["status"] == "done" and step["actor"] == "user" and step["params"]["image"] == lincoln
        out = step["outputs"][0]
        await c.event("step.started", lambda p: p["step"]["id"] == step["id"])
        finished = await c.event("step.finished", lambda p: p["step"]["id"] == step["id"])
        assert [a["id"] for a in finished["artifacts"]] == [out]

        got = await c.call("artifacts.get", id=out)
        assert base64.b64decode(got["data"]) == app.session.artifacts.data(out)
        assert got["mime"] == "image/png" and (got["meta"]["width"], got["meta"]["height"]) == (250, 280)
        thumb = await c.call("artifacts.get", id=out[:6], max_px=64)
        with Image.open(io.BytesIO(base64.b64decode(thumb["data"]))) as im:
            assert thumb["mime"] == "image/png" and im.format == "PNG" and im.size == (57, 64)
        with pytest.raises(Failed) as e:
            await c.call("artifacts.get", id="ffffff")
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "no such artifact: ffffff"
        with pytest.raises(Failed) as e:
            await c.call("artifacts.get", id=out, max_px=5)
        assert e.value.code == rpc.INVALID_PARAMS

        # an engine failure is a failed step, not an RPC error; bad parameters are an RPC error
        failed = await c.call("tools.run", tool="cutout",
                              params={"image": lincoln, "box": [900, 900, 950, 950], "no_ai": True})
        assert failed["status"] == "error" and "empty" in failed["error"]["message"]
        await c.event("step.failed", lambda p: p["step"]["id"] == failed["id"])
        with pytest.raises(Failed) as e:
            await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": "big"})
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "bad parameters for cutout"

        snap = await c.call("session.get")
        assert [s["status"] for s in snap["steps"]] == ["done", "error"]
        assert snap["schema"] == 1 and snap["id"] == app.session.data.id and snap["path"] is None
        assert snap["turn_running"] is False and snap["pending_approvals"] == []

    run(body)


def test_a_pasted_image_has_the_import_limit_and_is_decoded_off_the_loop(env, monkeypatch):
    """artifacts.import's `data` has the same MAX_IMPORT_BYTES limit as a picked file, checked on the base64
    length before anything is decoded; and it is decoded in the locked call's thread, never on the event
    loop, so a big paste doesn't stall every client."""
    decoded_in: list[threading.Thread] = []
    decode = server_app._decode_paste

    def spy(data: str) -> bytes:
        decoded_in.append(threading.current_thread())
        return decode(data)

    monkeypatch.setattr(server_app, "_decode_paste", spy)

    async def body(app):
        c = Client(app)
        # lincoln.png is 249419 bytes, so its base64 ends in "=": the limit is on the decoded size exactly
        monkeypatch.setattr(server_app, "MAX_IMPORT_BYTES", len(LINCOLN) - 1)
        with pytest.raises(Failed) as e:
            await imported(c)
        assert (e.value.code, e.value.message) == (rpc.ENGINE_ERROR, "lincoln.png is too big to import")
        assert e.value.data["hint"].startswith("the limit is ")
        with pytest.raises(Failed) as e:  # too big is known from the length alone: this is never decoded
            await c.call("artifacts.import", data="!" * (2 * len(LINCOLN)))
        assert e.value.message == "the pasted image is too big to import"
        assert decoded_in == [] and app.session.artifacts.ids() == []
        monkeypatch.setattr(server_app, "MAX_IMPORT_BYTES", len(LINCOLN))  # the limit itself is allowed
        assert app.session.artifacts.meta[await imported(c)].label == "lincoln_work"
        assert len(decoded_in) == 1 and decoded_in[0] is not threading.main_thread()  # the loop's thread
        with pytest.raises(Failed) as e:  # within the limit, bad base64 is still refused (in the thread)
            await c.call("artifacts.import", data="not base64!")
        assert e.value.code == rpc.INVALID_PARAMS and e.value.message == "data is not base64"

    run(body)


def test_untrusted_actor_rules_and_approvals(env):
    async def body(app):
        user, cli = Client(app), Client(app, "cli:claude")
        lincoln = await imported(user)
        for method, params in (("session.get", {}), ("session.new", {}), ("session.restore", {}),
                               ("settings.set", {"values": {}}),
                               ("artifacts.import", {"path": str(TRUMP)}),
                               ("export", {"artifact_id": lincoln}),
                               ("approval.respond", {"step_id": "s1", "decision": "approve"}),
                               ("chat.send", {"text": "hi"}), ("steps.delete", {"step_id": "s1"})):
            with pytest.raises(Failed) as e:
                await cli.call(method, **params)
            assert e.value.code == rpc.FORBIDDEN, method

        cli_tools = {t["name"]: t for t in await cli.call("tools.list")}
        user_tools = {t["name"]: t for t in await user.call("tools.list")}
        assert "clipboard" not in cli_tools["fetch"]["schema"]["properties"]
        assert "clipboard" in user_tools["fetch"]["schema"]["properties"]
        assert cli_tools["export"]["writes_files"] and not cli_tools["export"]["mutates"]
        assert cli_tools["find"]["read_only"] and cli_tools["fetch"]["network"]
        assert set(cli_tools["cutout"]) == {"name", "summary", "description", "category", "mutates",
                                            "network", "read_only", "writes_files", "schema"}

        with pytest.raises(Failed) as e:  # a path is never an artifact id
            await cli.call("tools.run", tool="info", params={"image": str(TRUMP)})
        assert e.value.message == f"no such artifact: {TRUMP}"
        with pytest.raises(Failed) as e:
            await cli.call("tools.run", tool="fetch", params={"clipboard": True})
        assert e.value.message == "fetch: clipboard can only be set by the user"

        # ask_changes: read-only tools run at once, the rest wait for the user
        info = await cli.call("tools.run", tool="info", params={"image": lincoln[:8]})
        assert info["status"] == "done" and info["actor"] == "cli:claude"
        waiting = asyncio.create_task(cli.call("tools.run", tool="cutout", params={
            "image": lincoln, "box": [0, 0, 100, 100], "no_ai": True}))
        sid = await user.waiting()
        assert (await user.call("session.get"))["pending_approvals"] == [sid]
        for bad, code in (({"decision": "edit", "params": {"image": lincoln, "box": "x"}}, rpc.ENGINE_ERROR),
                          ({"decision": "edit"}, rpc.ENGINE_ERROR),
                          ({"decision": "maybe"}, rpc.INVALID_PARAMS)):
            with pytest.raises(Failed) as e:  # a bad answer is refused and the step keeps waiting
                await user.call("approval.respond", step_id=sid, **bad)
            assert e.value.code == code, bad
        with pytest.raises(Failed) as e:  # an image the session doesn't have: refused before anything runs
            await user.call("approval.respond", step_id=sid, decision="edit",
                            params={"image": "ffffff", "box": [10, 10, 60, 90], "no_ai": True})
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "no such artifact: ffffff"
        assert (await user.call("session.get"))["pending_approvals"] == [sid]
        assert app.session.step(sid).status == "proposed" and not waiting.done()
        await user.call("approval.respond", step_id=sid, decision="edit",
                        params={"image": lincoln, "box": [10, 10, 60, 90], "no_ai": True})
        step = await waiting
        assert step["status"] == "done" and step["params"]["box"] == [10, 10, 60, 90]
        assert app.session.artifacts.meta[step["outputs"][0]].width == 50

        rejected = asyncio.create_task(cli.call("tools.run", tool="filter",
                                                params={"image": lincoln, "names": ["invert"]}))
        sid = await user.waiting(lambda step: step["tool"] == "filter")
        await user.call("approval.respond", step_id=sid, decision="reject", note="not that")
        assert (await rejected)["status"] == "rejected"

        # a CLI agent that stops waiting (Task 13 cancels a closed connection's requests) leaves no step waiting
        gone = asyncio.create_task(cli.call("tools.run", tool="filter",
                                            params={"image": lincoln, "names": ["emboss"]}))
        sid = await user.waiting(lambda step: step["params"].get("names") == ["emboss"])
        gone.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gone
        assert app.session.step(sid).status == "rejected"
        assert (await user.call("session.get"))["pending_approvals"] == []
        with pytest.raises(Failed) as e:  # nothing is waiting for that step any more
            await user.call("approval.respond", step_id=sid, decision="approve")
        assert e.value.code == rpc.ENGINE_ERROR
        assert "proposed" not in {s.status for s in app.session.data.steps}

    run(body)


def test_an_edit_the_session_refuses_rejects_the_cli_step(env):
    """The backstop behind approval.respond's own checks: an edit that Session.run refuses (it does so before
    it changes the step) rejects the step in the same locked call, so it never stays proposed with nothing
    waiting for it."""
    session = Session.new(executor=InProcessExecutor())
    lincoln = session.import_image(LINCOLN, "lincoln.png").id
    step = session.propose("cutout", {"image": lincoln, "box": HEAD, "no_ai": True}, "cli:claude")
    refused = CoreApp._run_or_reject(session, step.id, {"image": "ffffff", "box": HEAD, "no_ai": True})
    assert refused.status == "rejected"
    assert refused.result_text == ("rejected by user: the edited parameters were refused: "
                                   "no such artifact: ffffff")
    with pytest.raises(EngineError):  # on its own params there is nothing to fall back to
        CoreApp._run_or_reject(session, step.id, None)
    ok = session.propose("cutout", {"image": lincoln, "box": HEAD, "no_ai": True}, "cli:claude")
    assert CoreApp._run_or_reject(session, ok.id, None).status == "done"
    assert CoreApp._settle(session, ok.id, "too late").status == "done"  # a step that ran stays as it is
    assert [s.status for s in session.data.steps] == ["rejected", "done"]


def test_cli_calls_follow_the_sessions_approval_mode(env):
    """Spec 7, "the same gate applies to CLI agents": whether a CLI agent's call waits is decided by the open
    session's mode (session.data.approval_mode) when the call is made, not by the settings' mode for new
    sessions. A switch applies from the next call, and an opened project brings its own mode."""
    async def body(app):
        user, cli = Client(app), Client(app, "cli:gemini")
        lincoln = await imported(user)
        assert (await user.call("session.get"))["approval_mode"] == "ask_all"  # a new session: the settings'
        info = asyncio.create_task(cli.call("tools.run", tool="info", params={"image": lincoln}))
        sid = await user.waiting(lambda step: step["tool"] == "info")  # ask_all: even a read-only tool waits
        await user.call("approval.respond", step_id=sid, decision="approve")
        assert (await info)["status"] == "done"

        await user.call("session.set_approval_mode", mode="auto")
        cut = await asyncio.wait_for(cli.call("tools.run", tool="cutout", params={
            "image": lincoln, "box": HEAD, "no_ai": True}), 10)  # auto: it runs without asking
        assert cut["status"] == "done" and cut["actor"] == "cli:gemini"
        assert app.settings.approval_mode == "ask_all"  # the session's mode decided, not the settings'
        saved = await user.call("session.save_as", path=str(env / "auto.badshop"))

        await user.call("session.set_approval_mode", mode="ask_changes")
        assert (await cli.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"
        filtered = asyncio.create_task(cli.call("tools.run", tool="filter",
                                                params={"image": lincoln, "names": ["invert"]}))
        sid = await user.waiting(lambda step: step["tool"] == "filter")  # ask_changes: a change waits
        await user.call("approval.respond", step_id=sid, decision="reject", note="not now")
        assert (await filtered)["status"] == "rejected"

        opened = await user.call("session.open", path=saved["path"])  # saved while the mode was auto
        assert opened["approval_mode"] == "auto"
        again = await asyncio.wait_for(cli.call("tools.run", tool="filter", params={
            "image": lincoln, "names": ["invert"]}), 10)
        assert again["status"] == "done" and again["actor"] == "cli:gemini"
        # only the two calls their session's mode held back ever waited
        assert [e["params"]["step"]["tool"] for e in user.events if e["method"] == "approval.needed"] == [
            "info", "filter"]

    run(body, Settings(approval_mode="ask_all"))


def test_edit_replays_the_later_steps(env):
    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        cut = await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        pasted = await c.call("tools.run", tool="paste", params={"base": lincoln, "piece": cut["outputs"][0],
                                                                  "fit_box": [0, 0, 200, 200]})
        edited = await c.call("steps.edit", step_id=cut["id"],
                              params={"image": lincoln, "box": [100, 50, 300, 300], "no_ai": True})
        assert edited == {"stale": [cut["id"], pasted["id"]]}
        assert (await c.event("step.stale")) == {"step_ids": [cut["id"], pasted["id"]]}
        # auto_replay: the replay runs by itself after the edit returns
        await c.event("step.finished", lambda p: p["step"]["id"] == pasted["id"]
                      and p["step"]["outputs"] != pasted["outputs"])
        steps = (await c.call("session.get"))["steps"]
        assert [s["status"] for s in steps] == ["done", "done"]
        assert steps[1]["params"]["piece"] == steps[0]["outputs"][0] != cut["outputs"][0]

        await c.call("settings.set", values={"auto_replay": False})
        await c.call("steps.edit", step_id=cut["id"], params={"image": lincoln, "box": [100, 50, 250, 250],
                                                              "no_ai": True})
        assert [s["status"] for s in (await c.call("session.get"))["steps"]] == ["stale", "stale"]
        replayed = await c.call("steps.replay_from", step_id=cut["id"])
        assert [(s["id"], s["status"]) for s in replayed] == [(cut["id"], "done"), (pasted["id"], "done")]

        with pytest.raises(Failed) as e:  # only the last step can go (spec 7)
            await c.call("steps.delete", step_id=cut["id"])
        assert e.value.code == rpc.ENGINE_ERROR
        assert await c.call("steps.delete", step_id=pasted["id"]) == {"deleted": pasted["id"]}
        assert [s["id"] for s in (await c.call("session.get"))["steps"]] == [cut["id"]]
        # the session's step.deleted reaches the client (ruling R7); the refused delete sent none
        assert await c.event("step.deleted") == {"step_id": pasted["id"]}
        assert [e["params"] for e in c.events if e["method"] == "step.deleted"] == [{"step_id": pasted["id"]}]

    run(body)


def test_project_files_export_and_modes(env):
    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        cut = await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        mode = await c.call("session.set_approval_mode", mode="ask_all")
        assert mode["approval_mode"] == "ask_all"
        with pytest.raises(Failed) as e:
            await c.call("session.set_approval_mode", mode="yolo")
        assert e.value.code == rpc.INVALID_PARAMS

        with pytest.raises(Failed) as e:
            await c.call("session.save")
        assert e.value.message == "this session has no project file yet"
        with pytest.raises(Failed) as e:
            await c.call("session.save_as", path="relative.badshop")
        assert "absolute" in e.value.message
        saved = await c.call("session.save_as", path=str(env / "one.badshop"))
        assert Path(saved["path"]).is_file() and (await c.call("session.get"))["path"] == saved["path"]
        assert await c.call("session.save") == saved
        recipe = await c.call("session.export_recipe", path=str(env / "recipe.json"))
        assert json.loads(Path(recipe["path"]).read_text(encoding="utf-8"))["steps"]

        exported = await c.call("export", artifact_id=cut["outputs"][0][:8], name="head")
        assert exported == {"path": str(env / "out" / "head.png")}
        assert (env / "out" / "head.png").read_bytes() == app.session.artifacts.data(cut["outputs"][0])
        with pytest.raises(Failed) as e:
            await c.call("export", artifact_id="ffffff")
        assert e.value.message == "no such artifact: ffffff"

        # a file that isn't a project is refused, and the open session is untouched
        before = await c.call("session.get")
        (env / "junk.badshop").write_bytes(b"not a zip")
        for bad in (env / "junk.badshop", env / "missing.badshop"):
            with pytest.raises(Failed) as e:
                await c.call("session.open", path=str(bad))
            assert e.value.code == rpc.ENGINE_ERROR
        assert await c.call("session.get") == before

        new = await c.call("session.new", name="second")
        assert new["name"] == "second" and new["steps"] == [] and new["path"] is None
        assert new["approval_mode"] == "ask_changes"  # new sessions start in the settings' mode
        with pytest.raises(Failed) as e:
            await c.call("session.new", name="")
        assert e.value.code == rpc.INVALID_PARAMS
        opened = await c.call("session.open", path=saved["path"])
        assert opened["path"] == saved["path"] and opened["approval_mode"] == "ask_all"
        assert [s["id"] for s in opened["steps"]] == [cut["id"]]
        got = await c.call("artifacts.get", id=cut["outputs"][0])
        assert base64.b64decode(got["data"]) == (env / "out" / "head.png").read_bytes()

    run(body)


def test_save_as_refuses_the_autosave_folder(env):
    """The autosave folder is badshop's: the next launch's claim_autosave moves session.badshop out of the
    way, so a project saved there would vanish from where the user put it. Save As refuses the folder (by
    the same test session.open uses to treat a file there as no project file), and writes nothing."""
    async def body(app):
        c = Client(app)
        await imported(c)  # a change: this run's autosave is written
        folder = project.autosave_path().parent
        (env / "link").symlink_to(folder, target_is_directory=True)
        for target in (project.autosave_path(), folder / "mine.badshop", folder / "mine", env / "link" / "x"):
            with pytest.raises(Failed) as e:
                await c.call("session.save_as", path=str(target))
            assert e.value.code == rpc.ENGINE_ERROR, target
            assert e.value.message == f"can't save a project in {folder}: it is badshop's autosave folder"
            assert e.value.data == {"hint": "pick another folder for the project"}
        assert (await c.call("session.get"))["path"] is None
        assert [p.name for p in folder.iterdir()] == ["session.badshop"]  # nothing was written there
        saved = await c.call("session.save_as", path=str(env / "mine.badshop"))  # any other folder is fine
        assert saved == {"path": str(env / "mine.badshop")}

    run(body)


def test_the_next_launch_offers_the_last_autosave(env):
    """Spec 9 and 10: after a crash (or a quit) the next launch offers to restore the last run's autosave.
    CoreApp moves it aside as it starts (project.claim_autosave), so the new run's own first change, which
    autosaves, can't overwrite it."""
    async def first_run(app):
        c = Client(app)
        assert (await c.call("session.get"))["restorable"] is None  # a first launch has nothing to offer
        with pytest.raises(Failed) as e:
            await c.call("session.restore")
        assert e.value.code == rpc.ENGINE_ERROR
        assert e.value.message == "there is no autosaved session to restore"
        lincoln = await imported(c)
        await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        assert project.find_autosave() == project.autosave_path()  # saved after the step, not at close

    async def next_run(app):
        c = Client(app)
        snap = await c.call("session.get")
        assert snap["steps"] == [] and snap["restorable"] is not None
        offered = Path(snap["restorable"])
        assert offered.read_bytes() == last_run and project.find_autosave() is None  # moved aside
        await imported(c, TRUMP.read_bytes(), "trump.png")  # this run's first change autosaves...
        assert project.find_autosave() is not None
        assert offered.read_bytes() == last_run  # ...and the offer survives it
        assert (await c.call("session.get"))["restorable"] == str(offered)

        restored = await c.call("session.restore")
        assert [s["tool"] for s in restored["steps"]] == ["cutout"]
        assert restored["path"] is None  # the autosave is not the user's project file
        assert restored["restorable"] is None  # the offer is used up
        got = await c.call("artifacts.get", id=restored["steps"][0]["outputs"][0])
        assert (got["meta"]["width"], got["meta"]["height"]) == (250, 280)
        with pytest.raises(Failed) as e:
            await c.call("session.save")
        assert e.value.message == "this session has no project file yet"
        with pytest.raises(Failed) as e:
            await c.call("session.restore")
        assert e.value.message == "there is no autosaved session to restore"
        # from now on this run's autosave holds the restored session
        autosaved = project.open_project(project.autosave_path(), executor=InProcessExecutor())
        assert [s.tool for s in autosaved.data.steps] == ["cutout"]
        # opening a file in the autosave folder by hand doesn't make it the project file either
        assert (await c.call("session.open", path=str(offered)))["path"] is None

    run(first_run)
    last_run = project.autosave_path().read_bytes()
    run(next_run)


def test_chat_turn_with_an_approval(env):
    async def body(app):
        c = Client(app)
        with pytest.raises(Failed) as e:
            await c.call("chat.send", text="hi")
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "no model provider is set up yet"
        await c.call("settings.set", values={"fake_provider_script": str(env / "missing.json")})
        with pytest.raises(Failed) as e:
            await c.call("chat.send", text="hi")
        assert e.value.code == rpc.ENGINE_ERROR
        assert e.value.message.startswith("can't read the fake provider script")
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "Let me measure it.",
             "tool_calls": [{"name": "info", "arguments": {"image": lincoln[:8]}}]},
            {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": lincoln[:8], "box": HEAD,
                                                                          "no_ai": True}}]},
            {"text": "Here is his head.", "tool_calls": []},
        ])})
        with pytest.raises(Failed) as e:  # a bad attachment fails before any turn starts
            await c.call("chat.send", text="crop", attachments=["ffffff"])
        assert e.value.message == "no such artifact: ffffff"
        started = await c.call("chat.send", text="crop lincoln's head", attachments=[lincoln[:8]])
        assert started == {"started": True}

        needed = await c.event("approval.needed")
        assert needed["step"]["tool"] == "cutout" and needed["step"]["actor"] == "agent:fake"
        snap = await c.call("session.get")
        assert snap["turn_running"] and snap["pending_approvals"] == [needed["step"]["id"]]
        for method, params in (("chat.send", {"text": "again"}), ("session.new", {}), ("session.restore", {}),
                               ("session.open", {"path": str(env / "other.badshop")})):
            with pytest.raises(Failed) as e:  # one turn at a time; the session stays while it runs
                await c.call(method, **params)
            assert e.value.message == "the agent is still working", method
        await c.call("approval.respond", step_id=needed["step"]["id"], decision="edit",
                     params={"image": lincoln, "box": [100, 50, 300, 300], "no_ai": True})

        assert await c.event("turn.finished") == {"reason": "done"}
        await idle(c)
        steps = app.session.data.steps
        assert [(s.tool, s.status, s.actor) for s in steps] == [("info", "done", "agent:fake"),
                                                                ("cutout", "done", "agent:fake")]
        assert steps[1].params["box"] == [100, 50, 300, 300]
        streamed = "".join(e["params"]["text"] for e in c.events if e["method"] == "message.delta")
        assert "Let me measure it." in streamed and "Here is his head." in streamed
        m = c.methods()
        assert m.index("turn.started") < m.index("approval.needed") < m.index("approval.resolved") < \
            m.index("turn.finished")

    run(body)


def test_switching_the_approval_mode_mid_turn(env):
    """session.set_approval_mode while a turn runs: the turn follows the new mode from its next tool call
    (run_turn reads cfg.approval_mode at every call, and CoreApp assigns it), whether the switch asks for
    more approvals or for fewer. The call already waiting keeps waiting."""
    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": lincoln, "box": HEAD,
                                                                          "no_ai": True}}]},
            {"text": "", "tool_calls": [{"name": "info", "arguments": {"image": lincoln}}]},
            {"text": "", "tool_calls": [{"name": "filter", "arguments": {"image": lincoln,
                                                                          "names": ["invert"]}}]},
            {"text": "All done.", "tool_calls": []},
        ])})
        await c.call("chat.send", text="go")
        cut = await c.waiting(lambda step: step["tool"] == "cutout")  # ask_changes: a change waits
        snap = await c.call("session.set_approval_mode", mode="ask_all")
        assert snap["approval_mode"] == "ask_all" and snap["turn_running"]
        assert snap["pending_approvals"] == [cut]  # the call already waiting keeps waiting
        await c.call("approval.respond", step_id=cut, decision="approve")
        info = await c.waiting(lambda step: step["tool"] == "info")  # ask_all: now a read-only tool waits too
        await c.call("session.set_approval_mode", mode="auto")
        await c.call("approval.respond", step_id=info, decision="approve")
        assert await c.event("turn.finished") == {"reason": "done"}  # auto: the filter ran without asking
        snap = await idle(c)
        assert [(s["tool"], s["status"]) for s in snap["steps"]] == [("cutout", "done"), ("info", "done"),
                                                                     ("filter", "done")]
        assert [e["params"]["step"]["tool"] for e in c.events if e["method"] == "approval.needed"] == [
            "cutout", "info"]
        # the switch is the session's: the settings' mode for new sessions is unchanged
        assert snap["approval_mode"] == "auto" and app.settings.approval_mode == "ask_changes"

    run(body)


def test_stop_and_client_gone(env):
    """Review focus 1 at the app level: Stop ends the chat's turn and leaves a CLI agent's call waiting;
    when the UI goes away mid-turn, the turn stops cleanly, every pending approval (the agent's and a CLI
    agent's) is rejected, and the core keeps serving."""
    async def body(app):
        c, cli = Client(app), Client(app, "cli:codex")
        lincoln = await imported(c)
        cut = {"name": "cutout", "arguments": {"image": lincoln, "box": [0, 0, 100, 100], "no_ai": True}}
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "one", "tool_calls": [cut]}, {"text": "two", "tool_calls": [cut]}])})

        await c.call("chat.send", text="go")
        first = await c.waiting()
        waiting = asyncio.create_task(cli.call("tools.run", tool="filter",
                                               params={"image": lincoln, "names": ["invert"]}))
        third = await c.waiting(lambda step: step["actor"] == "cli:codex")
        assert (await c.call("session.get"))["pending_approvals"] == [first, third]
        assert await c.call("chat.stop") == {"stopped": True}
        assert await c.event("turn.finished") == {"reason": "stopped"}
        assert app.session.step(first).status == "rejected"
        # Stop is about the chat: the CLI agent's call still waits for the user
        assert (await c.call("session.get"))["pending_approvals"] == [third]
        assert app.session.step(third).status == "proposed" and not waiting.done()
        assert await c.call("chat.stop") == {"stopped": False}

        await c.call("chat.send", text="again")
        second = await cli.waiting(lambda step: step["actor"] == "agent:fake" and step["id"] != first)
        c.unsubscribe()
        app.on_client_gone()
        assert (await waiting)["status"] == "rejected"
        await cli.count("turn.finished", 2)
        assert [e["params"] for e in cli.events if e["method"] == "turn.finished"][-1] == {"reason": "stopped"}

        later = Client(app)  # the UI reconnects
        snap = await idle(later)
        steps = {s["id"]: s for s in snap["steps"]}
        assert [steps[i]["status"] for i in (first, second, third)] == ["rejected"] * 3
        assert steps[third]["result_text"] == "rejected by user: the user closed the app"
        assert snap["pending_approvals"] == [] and "proposed" not in {s["status"] for s in snap["steps"]}
        assert (await later.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"

    run(body)


class HangingFirstCall(InProcessExecutor):
    """The first tool call hangs until it is stopped, by its own cancel event (a turn's Stop) or by cancel()
    (or a test setting `released`); later calls run normally. Counts cancel() and close()."""

    def __init__(self):
        self.started, self.released = threading.Event(), threading.Event()
        self.calls = self.cancels = self.closes = 0
        self.stopped_by: str | None = None

    def run(self, call, cancel=None):
        self.calls += 1
        if self.calls > 1:
            return super().run(call, cancel)
        self.started.set()
        for _ in range(1000):  # up to 10 s
            if self.released.wait(0.01) or (cancel is not None and cancel.is_set()):
                self.stopped_by = "cancel()" if self.released.is_set() else "its event"
                return ToolOutcome(ok=False, error_message="stopped by the user")
        raise AssertionError("never stopped")

    def cancel(self):
        self.cancels += 1
        self.released.set()

    def close(self):
        self.closes += 1


def test_stop_while_a_tool_runs(env):
    ex = HangingFirstCall()

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("session.set_approval_mode", mode="auto")
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": lincoln, "box": HEAD,
                                                                          "no_ai": True}}]}])})
        await c.call("chat.send", text="go")
        assert await asyncio.to_thread(ex.started.wait, 10)
        assert await c.call("chat.stop") == {"stopped": True}  # returns once the tool's thread has ended
        assert ex.stopped_by == "its event" and ex.cancels == 0  # the turn's Stop reached this very call
        step = app.session.data.steps[-1]
        assert step.status == "error" and step.error.message == "stopped by the user"
        # the autosave holds the turn as it ended: the stopped call has its answer, as in memory
        transcript = app.session.data.transcript
        assert transcript[-1] == {"role": "tool", "tool_call_id": "call_1", "content": step.result_text}
        assert project.open_project(project.autosave_path()).data.transcript == transcript
        assert (await c.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"

    run(body, factory=lambda **limits: ex)
    assert ex.closes == 1  # close() closed the executor


def test_settings_apply_to_the_running_app(env):
    made: list[tuple[dict, HangingFirstCall]] = []

    def factory(**limits):
        ex = HangingFirstCall()
        ex.calls = 1  # never hang
        made.append((limits, ex))
        return ex

    async def body(app):
        c = Client(app)
        assert [limits for limits, _ in made] == [{"timeout_s": 120.0, "max_rss_mb": 3072}]
        got = await c.call("settings.set", values={"tool_timeout_s": 5, "output_dir": str(env / "elsewhere")})
        assert got["tool_timeout_s"] == 5.0 and load_settings() == Settings(**got)
        assert made[-1][0] == {"timeout_s": 5.0, "max_rss_mb": 3072}
        assert made[0][1].closes == 1 and app.session.executor is made[-1][1]
        await c.call("settings.set", values={"auto_replay": False})
        assert len(made) == 2  # unchanged limits keep the executor
        with pytest.raises(Failed) as e:
            await c.call("settings.set", values={"step_budget": 0})
        assert e.value.code == rpc.INVALID_PARAMS and "step_budget" in e.value.data["hint"]
        with pytest.raises(Failed) as e:
            await c.call("settings.set", values={"bogus": 1})
        assert e.value.code == rpc.INVALID_PARAMS
        assert (await c.call("settings.get"))["step_budget"] == 40
        lincoln = await imported(c)  # labelled lincoln_work: the working copy
        assert (await c.call("export", artifact_id=lincoln))["path"] == str(env / "elsewhere" /
                                                                            "lincoln_work.png")

    run(body, factory=factory)
    assert [ex.closes for _, ex in made] == [1, 1]


def test_settings_changes_queued_behind_a_tool_all_apply(env):
    """settings.set merges its values into the settings as they are once its turn under the lock comes, so
    changes queued behind a running tool (a settings page may send one per field) apply in order and none
    is lost, in the app and in settings.json. A bad value queued with them is still INVALID_PARAMS."""
    ex = HangingFirstCall()

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        busy = asyncio.create_task(c.call("tools.run", tool="info", params={"image": lincoln}))
        assert await asyncio.to_thread(ex.started.wait, 10)  # the user's tool holds the lock
        first = asyncio.create_task(c.call("settings.set", values={"auto_replay": False}))
        bad = asyncio.create_task(c.call("settings.set", values={"step_budget": 0}))
        second = asyncio.create_task(c.call("settings.set", values={"step_budget": 7}))
        await asyncio.sleep(0)  # all three run up to the lock and wait there, in order
        ex.released.set()
        assert (await busy)["status"] == "error"
        assert (await first)["auto_replay"] is False
        with pytest.raises(Failed) as e:
            await bad
        assert e.value.code == rpc.INVALID_PARAMS and "step_budget" in e.value.data["hint"]
        both = Settings(auto_replay=False, step_budget=7)
        assert await second == both.model_dump(mode="json")
        assert app.settings == load_settings() == both

    run(body, factory=lambda **limits: ex)


def test_a_bad_settings_file_or_home_folder_never_breaks_the_core(env):
    """A settings.json that load_settings can't use still lets the core start (with what it could keep), and a
    "~name" path for a user this computer doesn't have is a clean error, never an internal one."""
    async def start():
        app = CoreApp(executor_factory=in_process)  # no settings given: it loads settings.json
        try:
            return app.settings
        finally:
            await app.close()

    config_dir().mkdir(parents=True)
    no_home = json.dumps({"output_dir": f"{NO_HOME}/pics", "step_budget": 7})
    for text, kept in ((no_home, Settings(step_budget=7)), ("[" * 100_000, Settings())):
        settings_path().write_text(text, encoding="utf-8")
        assert asyncio.run(start()) == kept

    async def body(app):
        c = Client(app)
        for method, params in (("session.open", {"path": f"{NO_HOME}/x.badshop"}),
                               ("session.save_as", {"path": f"{NO_HOME}/x.badshop"}),
                               ("session.export_recipe", {"path": f"{NO_HOME}/recipe.json"}),
                               ("artifacts.import", {"path": f"{NO_HOME}/x.png"})):
            with pytest.raises(Failed) as e:
                await c.call(method, **params)
            assert (e.value.code, e.value.message) == (rpc.ENGINE_ERROR,
                                                       f"{params['path']} is not an absolute path"), method
            assert e.value.data == {"hint": "pick the file with the file dialog"}
        with pytest.raises(Failed) as e:
            await c.call("settings.set", values={"output_dir": f"{NO_HOME}/pics"})
        assert e.value.code == rpc.INVALID_PARAMS and "output_dir" in e.value.data["hint"]
        assert app.settings == Settings() and (await c.call("session.get"))["path"] is None

    run(body)


def test_no_turn_starts_while_the_session_is_being_replaced(env):
    ex = HangingFirstCall()

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [{"text": "hello"}])})
        busy = asyncio.create_task(c.call("tools.run", tool="info", params={"image": lincoln}))
        assert await asyncio.to_thread(ex.started.wait, 10)  # the user's tool holds the lock
        new = asyncio.create_task(c.call("session.new", name="next"))
        await asyncio.sleep(0)  # session.new runs up to the lock and waits there
        with pytest.raises(Failed) as e:  # a turn started now would run on the session being replaced
            await c.call("chat.send", text="hi")
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "the session is being replaced"
        ex.released.set()
        assert (await busy)["status"] == "error"
        assert (await new)["name"] == "next"
        assert await c.call("chat.send", text="hi") == {"started": True}
        assert await c.event("turn.finished") == {"reason": "done"}
        assert [m["role"] for m in (await idle(c))["messages"]] == ["user", "assistant"]

    run(body, factory=lambda **limits: ex)


def test_a_replaced_session_sends_no_step_events(env):
    """Step ids start again at s1 in every session and events carry no session id, so once session.new,
    session.open or session.restore has replaced a session, nothing that session does reaches a client: the
    CLI step it rejects after the swap would otherwise land on the new session's step with the same id."""
    async def first_run(app):  # leaves an autosave to restore, and a project to open
        c = Client(app)
        lincoln = await imported(c)
        await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        await c.call("session.save_as", path=str(env / "saved.badshop"))

    async def next_run(app):
        ids = []  # (the replaced session's waiting CLI step, the new session's next step)
        for method, params in (("session.new", {}), ("session.open", {"path": str(env / "saved.badshop")}),
                               ("session.restore", {})):
            user, cli = Client(app), Client(app, "cli:claude")
            lincoln = await imported(user)
            waiting = asyncio.create_task(cli.call("tools.run", tool="filter",
                                                   params={"image": lincoln, "names": ["invert"]}))
            old = await user.waiting()
            mark = len(user.events)
            await user.call(method, **params)
            assert (await waiting)["status"] == "rejected"  # the CLI caller still gets its answer
            new = await user.call("tools.run", tool="info", params={"image": await imported(user)})
            await user.event("step.finished", lambda p: p["step"]["id"] == new["id"])  # events come in order
            after = [(e["method"], e["params"]["step"]["id"], e["params"]["step"]["tool"])
                     for e in user.events[mark:] if e["method"].startswith("step.")]
            assert after == [(m, new["id"], "info")
                             for m in ("step.proposed", "step.started", "step.finished")], method
            ids.append((old, new["id"]))
            user.unsubscribe()
            cli.unsubscribe()
        assert ids == [("s1", "s1"), ("s2", "s2"), ("s3", "s2")]  # after new and open: the same id

    run(first_run)
    run(next_run)


def test_failures_are_reported_and_the_core_keeps_serving(env, monkeypatch):
    async def broken_turn(*args, **kw):
        raise RuntimeError("kaput")

    def full_disk(session):
        raise EngineError("can't save the project (disk full)")

    def broken_replay(self, step_id, **kw):
        raise EngineError("replay broke")

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [{"text": "hi"}])})
        monkeypatch.setattr(server_app, "run_turn", broken_turn)
        assert await c.call("chat.send", text="hi") == {"started": True}
        assert await c.event("turn.finished") == {"reason": "error", "error": "RuntimeError: kaput"}
        assert await c.event("core.log") == {"level": "error",
                                             "message": "the agent turn failed (RuntimeError: kaput)"}
        assert (await idle(c))["turn_running"] is False

        monkeypatch.setattr(project, "autosave", full_disk)
        cut = await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        assert cut["status"] == "done"  # the step is fine; its autosave failed, and that is reported
        assert await c.event("core.log", lambda p: p["level"] == "warning") == {
            "level": "warning", "message": "autosave failed: can't save the project (disk full)"}

        monkeypatch.setattr(Session, "replay_from", broken_replay)
        await c.call("steps.edit", step_id=cut["id"],
                     params={"image": lincoln, "box": [100, 50, 300, 300], "no_ai": True})
        assert await c.event("core.log", lambda p: p["message"].startswith("replay")) == {
            "level": "warning", "message": "replay failed: replay broke"}
        assert (await c.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"

    run(body)


def test_assets_status_and_download_progress(env, monkeypatch):
    def fake_download(name: str) -> Path:  # what cached() does: report each chunk to assets.PROGRESS
        assets.PROGRESS(name, 5, 10)
        assets.PROGRESS(name, 10, 10)
        return env / "data" / name

    monkeypatch.setattr(manifest, "download", fake_download)
    before = assets.PROGRESS

    async def body(app):
        c = Client(app)
        status = await c.call("assets.status")
        assert status and all(set(a) == {"name", "label", "approx_mb", "present"} for a in status)
        name = status[0]["name"]
        assert await c.call("assets.download", name=name) == {"path": str(env / "data" / name)}
        await c.event("asset.progress", lambda p: p["done"] == 10)
        assert [e["params"] for e in c.events if e["method"] == "asset.progress"] == [
            {"name": name, "done": 5, "total": 10}, {"name": name, "done": 10, "total": 10}]

    run(body)
    assert assets.PROGRESS is before  # close() put the previous listener back


def test_close_stops_a_waiting_turn(env):
    async def main():
        app = CoreApp(Settings(), executor_factory=in_process)
        c = Client(app)
        lincoln = await imported(c)
        cut = {"name": "cutout", "arguments": {"image": lincoln, "no_ai": True}}
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "", "tool_calls": [cut]}])})
        await c.call("chat.send", text="go")
        sid = await c.waiting()
        app.on_client_gone()  # the window closes and the app quits at once: two stops overlap
        await app.close()
        await app.close()  # idempotent
        assert app.session.step(sid).status == "rejected"
        assert "turn.finished" in c.methods()
        assert project.find_autosave() is not None

    asyncio.run(main())
