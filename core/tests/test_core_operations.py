"""Offline provider compatibility, private diagnostics, and recoverable asset transfers."""
import asyncio
import hashlib
import json
import logging
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from badshop.agent.provider import ProviderError
from badshop.engine import assets
from badshop.providers import litellm_provider as adapter
from test_litellm_provider import chunk, complete, use_sdk


def test_json_fallback_preserves_images_and_normalizes_tool_history(monkeypatch):
    payload = {"text": "Looking.", "tool_calls": [{"name": "find", "arguments": {"image": "abcd"}}]}
    sdk = use_sdk(monkeypatch, [chunk(json.dumps(payload), finish="stop")])
    sdk.tools = False
    provider = adapter.LiteLLMProvider("openai/local")
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "old", "type": "function", "function": {"name": "view", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "old", "content": "rejected by user"}]
    reply, deltas = complete(provider, messages, [{"type": "function", "function": {"name": "find"}}])
    assert reply.text == "Looking." and deltas == [reply.text]
    assert reply.tool_calls[0].name == "find" and reply.tool_calls[0].arguments == {"image": "abcd"}
    assert reply.tool_calls[0].id
    assert "JSON" in provider.warnings[0]
    request = sdk.requests[0]
    assert request["response_format"] == {"type": "json_object"}
    assert "tools" not in request and "tool_choice" not in request
    assert request["messages"][1] == messages[0]
    assert all(m["role"] != "tool" and "tool_calls" not in m for m in request["messages"])
    assert "rejected by user" in json.dumps(request["messages"])


@pytest.mark.parametrize("payload", ["{bad", "[]", '{"text":12}', '{"tool_calls":[{}]}',
                                      '{"text":"ok","tool_calls":[{"name":"find","arguments":null}]}'])
def test_json_fallback_malformed_reply_never_runs_tools(monkeypatch, payload):
    sdk = use_sdk(monkeypatch, [chunk(payload, finish="stop")])
    sdk.tools = False
    deltas = []
    with pytest.raises(ProviderError, match="JSON"):
        asyncio.run(adapter.LiteLLMProvider("openai/local").complete([], [], deltas.append))
    assert deltas == [] and sdk.stream.closed


def test_json_fallback_cancel_closes_stream(monkeypatch):
    from test_litellm_provider import Stream
    sdk = use_sdk(monkeypatch, [])
    sdk.tools = False

    async def run():
        waiting = asyncio.Event()
        class Waiting(Stream):
            async def __aiter__(self):
                waiting.set()
                await asyncio.Event().wait()
                yield chunk()
        sdk.stream = Waiting([])
        task = asyncio.create_task(adapter.LiteLLMProvider("openai/local").complete([], [], lambda _: None))
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sdk.stream.closed
    asyncio.run(run())


def test_diagnostics_redacts_before_disk_and_report(tmp_path, monkeypatch):
    from badshop import diagnostics
    monkeypatch.setenv("OPENAI_API_KEY", "cloud-secret-123")
    diagnostics.register_secret("private-profile-key")
    path = diagnostics.configure_logging(tmp_path)
    logger = logging.getLogger("badshop.test")
    logger.warning("request failed api_key=raw-key Authorization: Bearer bearer-key "
                   "https://user:pass@example.com/x?token=query-key "
                   "cloud-secret-123 private-profile-key data:image/png;base64,PRIVATEPHOTO")
    logger.warning("event", extra={"data": {"token": "session-token", "safe": 42}})
    try:
        raise RuntimeError("exception-private-key")
    except RuntimeError:
        logger.exception("provider failed")
    disk = path.read_text()
    report = diagnostics.diagnostic_report(tmp_path)
    for secret in ("raw-key", "bearer-key", "user:pass", "query-key", "cloud-secret-123", "private-profile-key",
                   "PRIVATEPHOTO", "session-token", "exception-private-key"):
        assert secret not in disk and secret not in json.dumps(report)
    records = [json.loads(line) for line in disk.splitlines()]
    assert records[1]["data"]["safe"] == 42 and records[1]["data"]["token"] == "[redacted]"
    assert report["versions"]["badshop"] and report["os"] and report["log_lines"]
    assert len(report["log_lines"]) <= 200
    handler = next(h for h in logging.getLogger("badshop").handlers if getattr(h, "baseFilename", None) == str(path))
    assert handler.backupCount == 7 and handler.when == "MIDNIGHT"
    # An explicit rollover exercises the real handler instead of mocking logging internals.
    handler.doRollover()
    logger.info("after rollover")
    assert "after rollover" in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(list(tmp_path.glob("badshop.log.*"))) == 1


def test_diagnostics_report_bounds_tail_and_never_reads_environment(tmp_path, monkeypatch):
    from badshop import diagnostics
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-include-me")
    (tmp_path / "badshop.log").write_text("".join(f"line {n}\n" for n in range(400)))
    report = diagnostics.diagnostic_report(tmp_path)
    assert len(report["log_lines"]) == 200 and report["log_lines"][0] == "line 200"
    assert "do-not-include-me" not in json.dumps(report)


@pytest.fixture
def asset_server():
    state = {"body": b"x" * (assets.CHUNK * 3 + 23), "requests": [], "ignore_range": False,
             "bad_range": False, "etag": '"version1"', "cut": False, "range_416": False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            headers = dict(self.headers)
            state["requests"].append(headers)
            body = state["body"]
            requested = self.headers.get("Range")
            start = int(requested[6:-1]) if requested else 0
            use_range = requested and not state["ignore_range"] and self.headers.get("If-Range", state["etag"]) == state["etag"]
            if requested and state["range_416"]:
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206 if use_range else 200)
            self.send_header("ETag", state["etag"])
            if use_range:
                offset = start + 1 if state["bad_range"] else start
                self.send_header("Content-Range", f"bytes {offset}-{len(body)-1}/{len(body)}")
                body = body[start:]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body[:assets.CHUNK] if state["cut"] else body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/asset"
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


def interrupt_asset(tmp_path, state, url, *, pinned=True):
    dest = tmp_path / "model.bin"
    stop = threading.Event()
    kw = {"sha256": hashlib.sha256(state["body"]).hexdigest(), "size": len(state["body"])} if pinned else {}
    with pytest.raises(assets.DownloadCancelled):
        assets.cached("model", url, dest=dest, progress=lambda *_: stop.set(), cancel=stop.is_set, **kw)
    assert not dest.exists()
    return dest, kw


def test_asset_cancel_then_range_resume_is_checked(tmp_path, asset_server):
    state, url = asset_server
    dest, kw = interrupt_asset(tmp_path, state, url)
    progress = []
    assert assets.cached("model", url, dest=dest, progress=lambda *p: progress.append(p), **kw).read_bytes() == state["body"]
    assert state["requests"][1]["Range"].startswith("bytes=")
    assert state["requests"][1]["If-Range"] == '"version1"'
    assert progress[0][0] > 0 and progress[-1] == (len(state["body"]), len(state["body"]))
    assert list(tmp_path.iterdir()) == [dest]


@pytest.mark.parametrize("change", ["ignore_range", "range_416", "etag"])
def test_asset_restart_when_resume_cannot_be_honored(tmp_path, asset_server, change):
    state, url = asset_server
    dest, kw = interrupt_asset(tmp_path, state, url)
    state[change] = '"version2"' if change == "etag" else True
    assert assets.cached("model", url, dest=dest, **kw).read_bytes() == state["body"]


def test_asset_bad_content_range_is_discarded(tmp_path, asset_server):
    state, url = asset_server
    dest, kw = interrupt_asset(tmp_path, state, url)
    state["bad_range"] = True
    with pytest.raises(assets.EngineError, match="range"):
        assets.cached("model", url, dest=dest, **kw)
    assert not dest.exists() and list(tmp_path.iterdir()) == []


def test_asset_short_transfer_resumes_and_verifies(tmp_path, asset_server):
    state, url = asset_server
    dest = tmp_path / "model.bin"
    state["cut"] = True
    with pytest.raises(assets.EngineError, match="cut short"):
        assets.cached("model", url, dest=dest)
    state["cut"] = False
    assert assets.cached("model", url, dest=dest).read_bytes() == state["body"]
    assert "Range" in state["requests"][-1]


def test_asset_resumed_corruption_fails_checksum_and_clears_partial(tmp_path, asset_server):
    state, url = asset_server
    dest, kw = interrupt_asset(tmp_path, state, url)
    partial = next(tmp_path.rglob("body"))
    original = partial.read_bytes()
    partial.write_bytes(b"z" + original[1:])
    with pytest.raises(assets.EngineError, match="checksum"):
        assets.cached("model", url, dest=dest, **kw)
    assert list(tmp_path.iterdir()) == []


def test_asset_cache_hit_checks_hash_not_only_size(tmp_path, asset_server):
    state, url = asset_server
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"z" * len(state["body"]))
    assert assets.cached("model", url, dest=dest, sha256=hashlib.sha256(state["body"]).hexdigest(), size=len(state["body"])).read_bytes() == state["body"]


def test_asset_process_cancel_hook(tmp_path, asset_server, monkeypatch):
    state, url = asset_server
    monkeypatch.setattr(assets, "CANCEL", lambda name: name == "model")
    with pytest.raises(assets.DownloadCancelled):
        assets.cached("model", url, dest=tmp_path / "model")
    assert not state["requests"]


def test_json_fallback_calls_keep_ordinary_validation_and_approval(monkeypatch, tmp_path):
    from test_agent import new_session, turn
    from test_litellm_provider import SDK, Stream
    session, image, events = new_session(tmp_path)
    payloads = [
        {"text": "bad arguments", "tool_calls": [{"name": "info", "arguments": {"image": 123}}]},
        {"text": "inspect", "tool_calls": [{"name": "info", "arguments": {"image": image.id}}]},
        {"text": "Finished.", "tool_calls": []},
    ]
    sdk = SDK([])
    sdk.tools = False
    async def request(**kwargs):
        sdk.requests.append(kwargs)
        return Stream([chunk(json.dumps(payloads.pop(0)), finish="stop")])
    sdk.acompletion = request
    monkeypatch.setattr(adapter, "_load_sdk", lambda: sdk)
    def reject(gate, step):
        gate.respond(step["id"], "reject", note="keep the image")
    reason, _ = turn(session, adapter.LiteLLMProvider("openai/local"), events, mode="ask_all", decide=reject)
    assert reason == "done"
    assert len(events.of("approval.needed")) == 1
    assert session.data.steps[0].status == "rejected"
    history = json.dumps(sdk.requests[1:])
    assert "error:" in history and "rejected by user: keep the image" in history


def test_diagnostics_report_includes_tail_across_rotation(tmp_path):
    from badshop import diagnostics
    (tmp_path / "badshop.log.2026-10-30").write_text("earlier line\n")
    (tmp_path / "badshop.log").write_text("latest line\n")
    assert diagnostics.diagnostic_report(tmp_path)["log_lines"] == ["earlier line", "latest line"]


def test_real_json_mode_transport_keeps_images(monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            payload = json.dumps({"text": "I see it.", "tool_calls": [{"name": "view", "arguments": {"image": "abcd1234"}}]})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            entry = chunk(payload, finish="stop")
            entry.update(id="chatcmpl-local", object="chat.completion.chunk", created=1, model="local")
            self.wfile.write(f"data: {json.dumps(entry)}\n\ndata: [DONE]\n\n".encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = adapter.LiteLLMProvider("openai/local", api_base=f"http://127.0.0.1:{server.server_port}/v1",
                                           capability_overrides={"vision": True, "tool_calls": False}, timeout_s=10)
        messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]
        async def run():
            try:
                return await provider.complete(messages, [{"type": "function", "function": {"name": "view"}}], lambda _: None)
            finally:
                await adapter.close_clients()
        reply = asyncio.run(run())
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
    assert reply.tool_calls[0].name == "view"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "tools" not in requests[0]
    assert requests[0]["messages"][1] == messages[0]


@pytest.mark.parametrize("pinned", [True, False])
@pytest.mark.parametrize("failure", ["offline", "timeout", "transient_http"])
def test_asset_failed_reconnect_preserves_partial_then_resumes(tmp_path, asset_server, monkeypatch, pinned, failure):
    import urllib.error
    state, url = asset_server
    dest, kw = interrupt_asset(tmp_path, state, url, pinned=pinned)
    partial = next(tmp_path.rglob("body"))
    original = partial.read_bytes()
    original_open = assets._open
    def cannot_connect(*args, **kwargs):
        if failure == "timeout":
            raise TimeoutError("reconnect timed out")
        if failure == "transient_http":
            raise urllib.error.HTTPError(url, 503, "try later", {}, None)
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(assets, "_open", cannot_connect)
    with pytest.raises(assets.EngineError, match="couldn't download"):
        assets.cached("model", url, dest=dest, **kw)
    assert next(tmp_path.rglob("body")).read_bytes() == original
    assert not dest.exists()
    monkeypatch.setattr(assets, "_open", original_open)
    assert assets.cached("model", url, dest=dest, **kw).read_bytes() == state["body"]
    assert state["requests"][-1]["Range"] == f"bytes={len(original)}-"
    assert state["requests"][-1]["If-Range"] == '"version1"'
    assert list(tmp_path.iterdir()) == [dest]
