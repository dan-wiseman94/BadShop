"""The WebSocket transport, the badshop-core entry point, and the whole core end to end (Task 13)."""

import asyncio
import base64
import hashlib
import itertools
import json
import signal
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from badshop import __version__
from badshop.server import main as core_main
from badshop.server import ws as transport
from badshop.server.ws import bound_port, serve
from badshop.session.artifacts import ArtifactStore
from badshop.session.execution import InProcessExecutor
from badshop.session.project import open_project
from badshop.session.session import Session
from conftest import FIXTURES, cli_env

TOKEN = "t0ken-for-tests"
WAIT_S = 120  # generous: the first tool call also starts the worker process


# ---- a JSON-RPC client over one connection -------------------------------------------------------------

class Client:
    """Sends one request at a time; keeps every notification it reads, in order, in `seen`."""

    def __init__(self, ws):
        self.ws = ws
        self.seen: list[dict] = []
        self._taken: set[int] = set()
        self._ids = itertools.count(1)

    async def _read(self) -> dict:
        return json.loads(await asyncio.wait_for(self.ws.recv(), WAIT_S))

    async def request(self, method: str, params: dict | None = None) -> dict:
        rid = next(self._ids)
        await self.ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                       "params": params or {}}))
        while True:
            msg = await self._read()
            if "id" not in msg:
                self.seen.append(msg)
            elif msg["id"] == rid:
                return msg

    async def call(self, method: str, params: dict | None = None):
        msg = await self.request(method, params)
        assert "error" not in msg, msg
        return msg["result"]

    async def fails(self, method: str, params: dict | None = None) -> dict:
        msg = await self.request(method, params)
        assert "error" in msg, msg
        return msg["error"]

    async def event(self, method: str) -> dict:
        """The params of the first notification called `method` not returned before, reading as needed."""
        while True:
            for i, e in enumerate(self.seen):
                if i not in self._taken and e["method"] == method:
                    self._taken.add(i)
                    return e["params"]
            msg = await self._read()
            assert "id" not in msg, f"a reply nobody asked for: {msg}"
            self.seen.append(msg)

    def methods(self) -> list[str]:
        return [e["method"] for e in self.seen]


@asynccontextmanager
async def client(port: int, token: str, actor: str = "user"):
    async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "token": token, "actor": actor}))
        welcome = json.loads(await asyncio.wait_for(ws.recv(), WAIT_S))
        assert welcome == {"type": "welcome", "actor": actor, "version": __version__}
        yield Client(ws)


async def closed_with(ws) -> int:
    """Read (and drop) whatever still arrives until the server closes the connection: its close code."""
    with pytest.raises(ConnectionClosed) as e:
        while True:
            await asyncio.wait_for(ws.recv(), WAIT_S)
    return e.value.rcvd.code


# ---- the transport, against a stand-in app -------------------------------------------------------------

class FakeApp:
    """What the transport uses of CoreApp: dispatcher.handle, subscribe and on_client_gone. Its methods:
    "who" answers with the caller's actor, "emit" sends an event first, "crash" raises (a bug), and "slow"
    waits for `release`; a cancelled "slow" takes a moment to clean up, as CoreApp waits for its thread."""

    def __init__(self):
        self.dispatcher = self
        self.subscribers = []
        self.gone = 0
        self.release = asyncio.Event()
        self.slow: list[int] = []  # ids of the "slow" calls that started
        self.cancelled: list[int] = []  # ids of the ones that were cancelled, once their cleanup is done

    async def handle(self, raw: str, actor: str) -> str | None:
        msg = json.loads(raw)
        if msg["method"] == "crash":
            raise RuntimeError("a bug in the app")
        if msg["method"] == "emit":
            for send in list(self.subscribers):
                await send(json.dumps({"jsonrpc": "2.0", "method": "ping", "params": msg["params"]}))
        if msg["method"] == "slow":
            self.slow.append(msg["id"])
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)
                self.cancelled.append(msg["id"])
                raise
        if "id" not in msg:
            return None
        return json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                           "result": {"method": msg["method"], "actor": actor}})

    def subscribe(self, send):
        self.subscribers.append(send)
        return lambda: self.subscribers.remove(send)

    def on_client_gone(self) -> None:
        self.gone += 1


@asynccontextmanager
async def fake_server():
    app = FakeApp()
    server = await serve(app, TOKEN)
    try:
        yield app, server
    finally:
        server.close()
        await server.wait_closed()


async def until(check) -> None:
    """Wait (at most 5 s) for the server side to catch up, e.g. to notice a closed connection."""
    for _ in range(500):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the server never got there")


def test_listens_on_loopback_and_answers_with_the_connection_actor():
    async def scenario():
        async with fake_server() as (app, server):
            host, port = server.sockets[0].getsockname()[:2]
            assert host == "127.0.0.1" and port == bound_port(server) > 0
            async with client(port, TOKEN, "user") as ui, client(port, TOKEN, "cli:codex") as cli:
                assert await ui.call("who") == {"method": "who", "actor": "user"}
                assert await cli.call("who") == {"method": "who", "actor": "cli:codex"}
                assert len(app.subscribers) == 2

    asyncio.run(scenario())


BAD_HELLOS = [json.dumps(h) for h in (
    {"type": "hello", "token": "wrong", "actor": "user"},
    {"type": "hello", "actor": "user"},
    {"type": "hello", "token": 12345, "actor": "user"},
    {"type": "hello", "token": "tökén", "actor": "user"},  # non-ASCII: compare_digest on str would raise
    {"type": "hello", "token": "\ud800", "actor": "user"},  # a lone surrogate can't even be encoded
    {"type": "hello", "token": TOKEN, "actor": "agent:fake"},  # agents run inside the core
    {"type": "hello", "token": TOKEN, "actor": "cli:cursor"},
    {"type": "hello", "token": TOKEN, "actor": "user\n"},  # `$` would match before a trailing newline
    {"type": "hello", "token": TOKEN},
    {"type": "hi", "token": TOKEN, "actor": "user"},
    ["hello", TOKEN, "user"],
)] + ["hello",  # not JSON
      "[" * 100_000]  # nested too deep: the JSON parser raises RecursionError, not ValueError


@pytest.mark.parametrize("hello", BAD_HELLOS, ids=range(len(BAD_HELLOS)))
def test_a_bad_hello_is_closed_with_1008(hello):
    async def scenario():
        async with fake_server() as (app, server):
            async with connect(f"ws://127.0.0.1:{bound_port(server)}") as ws:
                await ws.send(hello)
                assert await closed_with(ws) == 1008
            assert app.subscribers == [] and app.gone == 0  # never counted as a client

    asyncio.run(scenario())


def test_a_binary_first_message_or_no_hello_at_all_is_closed_with_1008(monkeypatch):
    monkeypatch.setattr(transport, "HELLO_TIMEOUT_S", 0.2)

    async def scenario():
        async with fake_server() as (app, server):
            url = f"ws://127.0.0.1:{bound_port(server)}"
            async with connect(url) as ws:
                await ws.send(json.dumps({"type": "hello", "token": TOKEN, "actor": "user"}).encode())
                assert await closed_with(ws) == 1008
            async with connect(url) as ws:  # says nothing
                assert await closed_with(ws) == 1008

    asyncio.run(scenario())


def test_binary_frames_after_the_hello_close_the_connection():
    async def scenario():
        async with fake_server() as (app, server):
            async with client(bound_port(server), TOKEN) as ui:
                await ui.ws.send(b'{"jsonrpc": "2.0", "id": 1, "method": "who"}')
                assert await closed_with(ui.ws) == 1003
            await until(lambda: app.gone == 1)

    asyncio.run(scenario())


def test_requests_run_concurrently_and_events_keep_their_order():
    async def scenario():
        async with fake_server() as (app, server):
            async with client(bound_port(server), TOKEN) as ui:
                for msg in ({"jsonrpc": "2.0", "id": 1, "method": "slow"},
                            {"jsonrpc": "2.0", "id": 2, "method": "emit", "params": {"n": 1}},
                            {"jsonrpc": "2.0", "method": "emit", "params": {"n": 2}}):
                    await ui.ws.send(json.dumps(msg))
                got = [json.loads(await asyncio.wait_for(ui.ws.recv(), WAIT_S)) for _ in range(3)]
                # the slow request holds up nothing; each event arrives before the reply that followed it
                assert got == [
                    {"jsonrpc": "2.0", "method": "ping", "params": {"n": 1}},
                    {"jsonrpc": "2.0", "id": 2, "result": {"method": "emit", "actor": "user"}},
                    {"jsonrpc": "2.0", "method": "ping", "params": {"n": 2}},
                ]
                app.release.set()
                reply = json.loads(await asyncio.wait_for(ui.ws.recv(), WAIT_S))
                assert reply == {"jsonrpc": "2.0", "id": 1, "result": {"method": "slow", "actor": "user"}}
            assert app.cancelled == []  # it had finished before the connection closed

    asyncio.run(scenario())


def test_a_request_the_app_fails_to_answer_still_gets_an_error_and_the_connection_goes_on(caplog):
    async def scenario():
        async with fake_server() as (app, server):
            async with client(bound_port(server), TOKEN) as ui:
                await ui.ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "crash"}))
                reply = json.loads(await asyncio.wait_for(ui.ws.recv(), WAIT_S))
                assert reply["id"] is None and reply["error"]["code"] == -32603
                assert await ui.call("who") == {"method": "who", "actor": "user"}

    asyncio.run(scenario())
    assert "a request crashed the dispatcher" in caplog.text


def test_a_closed_connection_cancels_its_requests_and_the_server_waits_for_them():
    async def scenario():
        app = FakeApp()
        server = await serve(app, TOKEN)
        try:
            port = bound_port(server)
            async with client(port, TOKEN) as ui:
                await ui.ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slow"}))
                await until(lambda: app.slow == [1])
            await until(lambda: app.cancelled == [1])  # the UI left: nobody is waiting for that answer
            async with client(port, TOKEN) as ui:
                await ui.ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "slow"}))
                await until(lambda: app.slow == [1, 2])
                server.close()  # what main does on SIGTERM
                assert await closed_with(ui.ws) == 1001  # going away
                await server.wait_closed()
                assert app.cancelled == [1, 2]  # wait_closed returned only after that request had ended
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_only_the_last_user_leaving_counts_as_the_ui_gone():
    async def scenario():
        async with fake_server() as (app, server):
            port = bound_port(server)
            async with client(port, TOKEN, "cli:claude"):
                async with client(port, TOKEN) as first:
                    async with client(port, TOKEN):
                        await until(lambda: len(app.subscribers) == 3)
                    await until(lambda: len(app.subscribers) == 2)
                    assert app.gone == 0  # another user client is still there
                    first.ws.transport.abort()  # the UI process dies: no close frame
                    await until(lambda: app.gone == 1)
                assert len(app.subscribers) == 1
            await until(lambda: app.subscribers == [])
            assert app.gone == 1  # a CLI agent leaving is not the UI closing

    asyncio.run(scenario())


def test_port_argument_is_checked(capsys):
    for bad in ("-1", "65536", "http"):
        with pytest.raises(SystemExit) as e:
            core_main.main(["serve", "--port", bad])
        assert e.value.code == 2
        assert "is not a port number" in capsys.readouterr().err


def test_a_busy_port_is_a_clean_error_and_changes_nothing(tmp_path):
    env = cli_env(tmp_path)
    env["BADSHOP_CONFIG_DIR"] = str(tmp_path / "config")
    env["BADSHOP_DATA_DIR"] = str(tmp_path / "data")
    last_run = tmp_path / "data" / "autosave" / "session.badshop"  # what the last run left
    last_run.parent.mkdir(parents=True)
    last_run.write_bytes(b"the last run's autosave")
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        p = subprocess.run([sys.executable, "-m", "badshop.server", "serve", "--port", str(port)],
                           cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
                           timeout=WAIT_S)
    assert p.returncode == 1 and p.stdout == ""  # no handshake line: the shell sees the exit
    assert f"can't listen on 127.0.0.1:{port}" in p.stderr and "Traceback" not in p.stderr
    # The start failed before the app existed, so the autosave was not set aside for a restore offer
    # this run will never make: the next start that does listen still offers it.
    assert [f.name for f in last_run.parent.iterdir()] == ["session.badshop"]
    assert last_run.read_bytes() == b"the last run's autosave"


# ---- the real core, as the desktop shell runs it -------------------------------------------------------

class Core:
    """A running `python -m badshop.server serve`: its port and token, and the two ways the desktop shell's
    going away reaches it."""

    def __init__(self, proc: asyncio.subprocess.Process, port: int, token: str):
        self.proc, self.port, self.token = proc, port, token
        self.stopped = False

    def stop(self) -> None:
        """SIGTERM, as the desktop shell sends when it quits (sent once, and not after hang_up)."""
        if not self.stopped:
            self.stopped = True
            self.proc.send_signal(signal.SIGTERM)

    def hang_up(self) -> None:
        """Close the core's stdin, as happens when the shell dies without stopping it (once, and not after
        stop)."""
        if not self.stopped:
            self.stopped = True
            self.proc.stdin.close()


@asynccontextmanager
async def core(root: Path, script: list | None = None, data: Path | None = None):
    """`python -m badshop.server serve` with the test caches, a private config folder, an optional
    fake-provider script and an optional private data folder (where the autosave goes; the default is the
    test cache's, which holds the fonts and models). Its stdin is a pipe the test never writes to, as the
    shell spawns it (spec §5.7): pytest's own stdin may be /dev/null (in CI, say), which would stop the
    core at once. Leaving the block stops the core with SIGTERM (unless the block stopped it or hung
    up) and checks a clean exit."""
    root.mkdir(parents=True, exist_ok=True)
    env = cli_env(root)
    env["BADSHOP_CONFIG_DIR"] = str(root / "config")
    if data is not None:
        env["BADSHOP_DATA_DIR"] = str(data)
    if script is not None:
        (root / "script.json").write_text(json.dumps(script), encoding="utf-8")
        env["BADSHOP_FAKE_PROVIDER"] = str(root / "script.json")
    log = root / "core.log"
    with open(log, "wb") as err:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "badshop.server", "serve", cwd=root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err)
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), WAIT_S)
            assert line, f"the core exited before its handshake:\n{log.read_text(encoding='utf-8')}"
            hello = json.loads(line)
            assert line == f'{{"port": {hello["port"]}, "token": "{hello["token"]}"}}\n'.encode()
            assert len(hello["token"]) >= 32
            running = Core(proc, hello["port"], hello["token"])
            yield running
            running.stop()
            assert await asyncio.wait_for(proc.wait(), WAIT_S) == 0, log.read_text(encoding="utf-8")
            assert await proc.stdout.read() == b""  # stdout carried the handshake and nothing else
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    assert "Traceback" not in log.read_text(encoding="utf-8")


def working_id(name: str) -> str:
    """The artifact id the core gives a fixture's working copy (imports are deterministic)."""
    return ArtifactStore().import_image((FIXTURES / f"{name}.png").read_bytes(), name)[0].id


def test_closing_the_ui_during_an_approval_stops_the_turn_and_the_core_keeps_serving(tmp_path):
    trump = working_id("trump")
    cut = {"name": "cutout", "arguments": {"image": trump, "box": [147, 159, 329, 330], "no_ai": True}}
    # Every reply asks for the same cutout, so the second turn asks again whether the core makes the
    # provider once or per turn.
    script = [{"text": "Cutting the face out.", "tool_calls": [cut]},
              {"text": "Once more.", "tool_calls": [cut]}]
    data = tmp_path / "data"  # private: the next launch finds the autosave this core leaves here

    async def scenario() -> None:
        async with core(tmp_path, script, data) as running:
            port, token = running.port, running.token
            async with client(port, token, "cli:claude") as watcher:
                async with client(port, token) as ui:
                    imported = await ui.call("artifacts.import", {"path": str(FIXTURES / "trump.png")})
                    assert imported["working"]["id"] == trump
                    sent = await ui.call("chat.send", {"text": "cut the face out", "attachments": [trump]})
                    assert sent == {"started": True}
                    first = (await ui.event("approval.needed"))["step"]
                    assert first["tool"] == "cutout" and first["status"] == "proposed"
                # the UI closed with the cutout still waiting: the turn stops
                assert await watcher.event("turn.finished") == {"reason": "stopped"}
                assert (await watcher.fails("session.get"))["code"] == -32001  # a user-only method
                async with client(port, token) as ui:  # the app comes back and sees the session
                    snap = await ui.call("session.get")
                    assert (snap["turn_running"], snap["pending_approvals"]) == (False, [])
                    assert snap["restorable"] is None  # the first launch: no earlier run to restore
                    step = snap["steps"][0]
                    assert (step["id"], step["tool"], step["status"]) == (first["id"], "cutout", "rejected")
                    gone = await ui.fails("approval.respond", {"step_id": step["id"], "decision": "approve"})
                    assert gone["code"] == -32000  # nothing waits for that approval any more
                    ran = await ui.call("tools.run", {"tool": "info", "params": {"image": trump}})
                    assert ran["status"] == "done" and ran["data"] == {"width": 474, "height": 600}
                    assert await ui.call("chat.send", {"text": "try again"}) == {"started": True}
                    second = (await ui.event("approval.needed"))["step"]
                    assert second["tool"] == "cutout"
                    # The shell quits with this cutout waiting: every client is told "going away".
                    running.stop()
                    assert await closed_with(ui.ws) == 1001
                assert await closed_with(watcher.ws) == 1001
        # Leaving `core` checked a clean exit (0), nothing more on stdout and no traceback. The next launch
        # offers what that core autosaved on the way out (spec §9), and it shows the second turn stopped
        # as if the UI had closed:
        async with core(tmp_path / "next", data=data) as relaunched:
            async with client(relaunched.port, relaunched.token) as ui:
                snap = await ui.call("session.get")
                assert snap["steps"] == []  # a new session, and the offer to restore the last one
                assert Path(snap["restorable"]) == data / "autosave" / "previous.badshop"
                restored = await ui.call("session.restore")
                assert restored["path"] is None  # the autosave is not the user's project file
                assert [(s["id"], s["status"]) for s in restored["steps"]] == [
                    (first["id"], "rejected"), (ran["id"], "done"), (second["id"], "rejected")]

    asyncio.run(scenario())


def running_ones(procs: list[psutil.Process]) -> list[psutil.Process]:
    """Those of `procs` that still run (one that has exited and only waits to be reaped has ended)."""
    alive = []
    for p in procs:
        try:
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                alive.append(p)
        except psutil.NoSuchProcess:
            pass
    return alive


def test_the_core_stops_cleanly_when_its_stdin_closes(tmp_path):
    """Spec §5.7, ruling R10: the shell spawns the core with a stdin pipe it never writes to. A shell that
    dies without stopping the core closes that pipe, and the core stops as it does on SIGTERM (clients get
    1001, the session is autosaved, the tool worker is closed, exit 0) instead of outliving it."""
    trump = working_id("trump")
    data = tmp_path / "data"  # private: the test reads back the autosave this core leaves

    async def scenario() -> str:
        async with core(tmp_path, data=data) as running:
            async with client(running.port, running.token) as ui:
                await ui.call("artifacts.import", {"path": str(FIXTURES / "trump.png")})
                ran = await ui.call("tools.run", {"tool": "info", "params": {"image": trump}})
                assert ran["status"] == "done" and ran["data"] == {"width": 474, "height": 600}
                started = psutil.Process(running.proc.pid).children(recursive=True)
                assert started  # the tool worker (and, on POSIX, multiprocessing's resource tracker)
                running.hang_up()  # the shell is gone: nothing holds the other end of the pipe any more
                assert await closed_with(ui.ws) == 1001  # the same clean stop as SIGTERM
            assert await asyncio.wait_for(running.proc.wait(), 10) == 0  # at once, not at some timeout
            await until(lambda: not running_ones(started))  # nothing the core started outlives it
        # Leaving `core` checked that nothing more came on stdout and that the log has no traceback.
        return ran["id"]

    step_id = asyncio.run(scenario())
    assert "badshop-core: stdin closed" in (tmp_path / "core.log").read_text(encoding="utf-8")
    autosaved = open_project(data / "autosave" / "session.badshop")
    assert [(s.id, s.tool, s.status) for s in autosaved.data.steps] == [(step_id, "info", "done")]
    assert trump in autosaved.data.artifacts


# The turn the fake provider plays: find (read-only, so it just runs), then cutout, paste and text, each
# waiting for approval (the default "ask_changes" mode). The user widens the cutout box before approving.
FIND = {"what": "faces"}
CUT = {"box": [147, 159, 329, 330], "oval": True}
CUT_EDITED = {"box": [140, 150, 336, 340], "oval": True}
PASTE = {"fit_box": [117, 123, 296, 310], "scale": 1.1}
CAPTION = {"text": "four score and seven memes ago", "bottom": True}


def expected_ids(out: Path) -> dict[str, str]:
    """The same work done in-process: the ids the core must produce (the engine is deterministic)."""
    s = Session.new(executor=InProcessExecutor(), output_dir=out)
    ids = {n: s.import_image((FIXTURES / f"{n}.png").read_bytes(), n).id for n in ("lincoln", "trump")}
    ids["cut"] = s.run_tool("cutout", {"image": ids["trump"], **CUT_EDITED}, "user").outputs[0]
    ids["pasted"] = s.run_tool("paste", {"base": ids["lincoln"], "piece": ids["cut"], **PASTE},
                               "user").outputs[0]
    ids["captioned"] = s.run_tool("text", {"image": ids["pasted"], **CAPTION}, "user").outputs[0]
    return ids


@pytest.mark.models  # find uses YuNet, and text the Impact lookalike font
def test_end_to_end_turn_save_reopen_and_replay(tmp_path):
    ids = expected_ids(tmp_path / "in-process")
    lincoln, trump = ids["lincoln"], ids["trump"]
    script = [
        {"text": "Finding the faces first.",
         "tool_calls": [{"name": "find", "arguments": {"image": trump, **FIND}}]},
        {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": trump, **CUT}}]},
        {"text": "", "tool_calls": [{"name": "paste", "arguments": {
            "base": lincoln[:8], "piece": ids["cut"], **PASTE}}]},  # a short ref, as models write them
        {"text": "", "tool_calls": [{"name": "text", "arguments": {"image": ids["pasted"], **CAPTION}}]},
        {"text": "Done: bad, as requested."},
    ]
    project = tmp_path / "trumpcoln.badshop"

    async def first_run() -> dict:
        async with core(tmp_path / "first", script) as running:
            async with connect(f"ws://127.0.0.1:{running.port}") as ws:
                await ws.send(json.dumps({"type": "hello", "token": running.token[:-1], "actor": "user"}))
                assert await closed_with(ws) == 1008
            async with client(running.port, running.token) as ui:
                for name in ("lincoln", "trump"):
                    got = await ui.call("artifacts.import", {"path": str(FIXTURES / f"{name}.png")})
                    assert got["working"]["id"] == ids[name]
                sent = await ui.call("chat.send", {"text": "put trump's face on lincoln",
                                                   "attachments": [lincoln, trump]})
                assert sent == {"started": True}

                need = (await ui.event("approval.needed"))["step"]
                assert need["tool"] == "cutout" and need["params"]["box"] == CUT["box"]
                ran = [e["params"]["step"]["tool"] for e in ui.seen if e["method"] == "step.finished"]
                assert ran == ["find"]  # read-only: it did not wait
                await ui.call("approval.respond", {"step_id": need["id"], "decision": "edit",
                                                   "params": {"image": trump, **CUT_EDITED}})
                for tool in ("paste", "text"):
                    need = (await ui.event("approval.needed"))["step"]
                    assert need["tool"] == tool
                    await ui.call("approval.respond", {"step_id": need["id"], "decision": "approve"})
                assert await ui.event("turn.finished") == {"reason": "done"}
                assert ui.methods()[0] == "turn.started"
                said = "".join(e["params"]["text"] for e in ui.seen if e["method"] == "message.delta")
                assert "Done: bad, as requested." in said
                finished = [e["params"]["step"] for e in ui.seen if e["method"] == "step.finished"]
                assert [(s["tool"], s["status"]) for s in finished] == [
                    ("find", "done"), ("cutout", "done"), ("paste", "done"), ("text", "done")]

                snap = await ui.call("session.get")
                steps = snap["steps"]
                assert [(s["tool"], s["actor"], s["status"]) for s in steps] == [
                    (tool, "agent:fake", "done") for tool in ("find", "cutout", "paste", "text")]
                assert steps[1]["params"]["box"] == CUT_EDITED["box"]  # the user's edit is what ran
                assert steps[2]["params"]["base"] == lincoln  # stored params hold full ids
                assert [s["outputs"][0] for s in steps[1:]] == [ids["cut"], ids["pasted"], ids["captioned"]]
                assert snap["artifacts"][ids["captioned"]]["produced_by"] == steps[3]["id"]
                got = await ui.call("artifacts.get", {"id": ids["captioned"]})
                assert hashlib.sha256(base64.b64decode(got["data"])).hexdigest() == ids["captioned"]

                saved = await ui.call("session.save_as", {"path": str(project)})
                assert Path(saved["path"]) == project and project.is_file()
                return snap

    async def second_run(before: dict) -> None:
        async with core(tmp_path / "second") as running:  # a new process: nothing carried over
            async with client(running.port, running.token) as ui:
                assert (await ui.call("session.get"))["steps"] == []
                reopened = await ui.call("session.open", {"path": str(project)})
                for key in ("messages", "steps", "artifacts"):
                    assert reopened[key] == before[key], key
                redo = [s["id"] for s in before["steps"][1:]]  # cutout, paste, text: the steps that make pixels
                # use_cache False: the reopened steps' own results would otherwise be reused, and nothing
                # would run at all
                replayed = await ui.call("steps.replay_from", {"step_id": redo[0], "use_cache": False})
                assert [s["id"] for s in replayed] == redo
                # every one of them really ran again: a reused result announces no step.started (events
                # leave before the reply that follows them, so they are all in `seen` by now) ...
                started = [e["params"]["step"]["id"] for e in ui.seen if e["method"] == "step.started"]
                assert started == redo
                # ... in this process's own tool worker, and made the same pixels, byte for byte
                # (spec §2, success criterion 4)
                assert [(s["status"], s["outputs"]) for s in replayed] == [
                    ("done", s["outputs"]) for s in before["steps"][1:]]
                after = (await ui.call("session.get"))["steps"]
                assert [(s["status"], s["outputs"]) for s in after] == [
                    ("done", s["outputs"]) for s in before["steps"]]

    asyncio.run(second_run(asyncio.run(first_run())))
