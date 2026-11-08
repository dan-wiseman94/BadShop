"""Privacy transitions through real RPC and the real API adapter, using only an owned server."""
import asyncio
import json
import threading
import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from badshop.server.settings import Settings, load_settings
from test_server_app import Client, Failed, env as env, run


def test_local_only_stops_active_api_before_acknowledgement(env):
    seen, release = threading.Event(), threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            seen.set()
            release.wait(10)
            delta = {"role": "assistant", "tool_calls": [{
                "index": 0, "id": "c1", "type": "function",
                "function": {"name": "canvas", "arguments": '{"width":32,"height":32,"background":"red"}'},
            }]} if len(requests) == 1 else {"role": "assistant", "content": "Done"}
            payload = "data: " + json.dumps({
                "id": "owned", "object": "chat.completion.chunk", "created": 1, "model": "owned",
                "choices": [{"index": 0, "delta": delta, "finish_reason": "tool_calls"}],
            }) + "\n\ndata: [DONE]\n\n"
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload.encode())))
                self.end_headers()
                self.wfile.write(payload.encode())
            except (BrokenPipeError, ConnectionResetError):
                pass  # cancellation deliberately closes this owned request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def body(app):
        client = Client(app)
        await client.call("tools.run", tool="canvas",
                          params={"width": 16, "height": 16, "background": "blue"})
        original = app.session.data.steps[0].outputs[0]
        profile = await client.call("providers.save", profile={
            "id": "owned-api", "kind": "api", "label": "Owned API", "model": "openai/owned",
            "api_base": f"http://127.0.0.1:{server.server_port}/v1",
            "capability_overrides": {"vision": True, "tool_calls": True},
        })
        await client.call("providers.select", profile_id=profile["id"])
        await client.call("chat.send", text="Create a red canvas")
        assert await asyncio.to_thread(seen.wait, 5)
        await client.call("settings.set", values={"no_remote": True})
        release.set()
        if app._turn:
            await asyncio.wait_for(asyncio.shield(app._turn), 5)
        assert len(requests) == 1, "an API request escaped after enabling Local only"
        assert not app._snapshot()["turn_running"]
        assert len(app.session.data.steps) == 1
        assert app.session.data.steps[0].outputs == [original]
        assert load_settings().no_remote
        await client.call("tools.run", tool="filter", params={"image": original, "names": ["invert"]})
        assert app.session.data.steps[-1].status == "done"

    try:
        run(body, Settings(approval_mode="auto"))
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_native_update_must_stop_before_local_only_is_acknowledged(env):
    from badshop.server.ws import serve, bound_port
    from badshop.server.auth import actor_token
    from websockets.asyncio.client import connect

    async def body(app):
        server = await serve(app, "private-test-token")
        try:
            async with connect(f"ws://127.0.0.1:{bound_port(server)}") as ws:
                await ws.send(json.dumps({"type": "hello", "actor": "updater", "token": actor_token("private-test-token", "updater")}))
                assert json.loads(await ws.recv())["type"] == "welcome"
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "updates.begin", "params": {}}))
                lease = json.loads(await ws.recv())["result"]["lease"]
                client = Client(app)
                toggle = asyncio.create_task(client.call("settings.set", values={"no_remote": True}))
                event = json.loads(await ws.recv())
                assert event["method"] == "updates.cancel"
                assert not toggle.done()
                assert not load_settings().no_remote
                with pytest.raises(Failed, match="Local only"):
                    await client.call("updates.begin")
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "updates.end", "params": {"lease": lease}}))
                assert json.loads(await ws.recv())["result"]["ended"]
                assert (await asyncio.wait_for(toggle, 2))["no_remote"]
                assert load_settings().no_remote
                with pytest.raises(Failed, match="Local only"):
                    await client.call("updates.begin")
                assert not app._update_leases
        finally:
            server.close()
            await server.wait_closed()
    run(body)


@pytest.mark.parametrize("phase", ["capabilities", "streaming"])
def test_local_only_cancels_test_connection_before_ack(env, monkeypatch, phase):
    entered, release = threading.Event(), threading.Event()
    calls, cancelled = [], []
    async def body(app):
        class Probe:
            def check_capabilities(self):
                if phase == "capabilities":
                    entered.set()
                    assert release.wait(10)
                return {"vision": True, "tool_calls": True}
            async def complete(self, *args):
                calls.append(app.settings.no_remote)
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)
        client = Client(app)
        await client.call("providers.save", profile={"id": "owned", "kind": "api", "label": "Owned", "model": "openai/owned"})
        monkeypatch.setattr(app, "_make_provider", lambda _: Probe())
        task = asyncio.create_task(client.call("providers.test", profile_id="owned", probe=True))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert (await client.call("settings.set", values={"no_remote": True}))["no_remote"]
            assert (await task)["status"] == "error"
            assert calls == ([] if phase == "capabilities" else [False])
            assert cancelled == ([] if phase == "capabilities" else [True])
            assert not app._provider_probes
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    run(body)


def test_updater_socket_cannot_keep_an_orphaned_agent_alive(env):
    from badshop.server.ws import serve, bound_port
    from test_server_ws import client as socket_client
    from test_server_app import script, idle
    async def body(app):
        server = await serve(app, "owned")
        observer = Client(app)
        try:
            async with socket_client(bound_port(server), "owned", "updater") as updater:
                lease = await updater.call("updates.begin")
                for method in ("settings.get", "session.get", "chat.stop", "tools.list"):
                    assert (await updater.fails(method))["code"] == -32001
                async with socket_client(bound_port(server), "owned") as renderer:
                    await renderer.call("settings.set", {"values": {"fake_provider_script": script(env, [
                        {"text": "", "tool_calls": [{"name": "canvas", "arguments": {"width": 16, "height": 16}}]}])}})
                    await renderer.call("chat.send", {"text": "make a canvas"})
                    await renderer.event("approval.needed")
                await observer.event("turn.finished")
                current = await idle(observer)
                assert not current["pending_approvals"]
                assert current["steps"][0]["status"] == "rejected"
                assert (await updater.call("updates.end", lease))["ended"]
        finally:
            server.close()
            await server.wait_closed()
    run(body, Settings(approval_mode="ask_all"))


def test_unacknowledged_native_update_never_claims_local_only(env, monkeypatch):
    monkeypatch.setattr("badshop.server.app.UPDATE_STOP_TIMEOUT_S", .02)
    async def body(app):
        client = Client(app)
        lease = await client.call("updates.begin")
        with pytest.raises(Failed, match="could not confirm"):
            await client.call("settings.set", values={"no_remote": True})
        assert not load_settings().no_remote
        assert not app.settings.no_remote
        await client.call("updates.end", **lease)
        assert (await client.call("settings.set", values={"no_remote": True}))["no_remote"]
        for method in ("updates.begin", "updates.end"):
            with pytest.raises(Failed):
                await Client(app, "cli:codex").call(method, **({"lease": "x"} if method.endswith("end") else {}))
    run(body)
