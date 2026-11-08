"""The documented Agent API wire format against a real loopback HTTP server."""

import asyncio
import base64
import hashlib
import io
import json
from contextlib import asynccontextmanager

import pytest
from PIL import Image

from badshop.agent.context import build_messages
from badshop.providers import perplexity_provider
from badshop.server.settings import Settings
from badshop.session import project
from test_server_app import Client, env as env, idle, imported, run

pytestmark = pytest.mark.integration

MODEL = "openai/gpt-5.6-sol"
KEY = "synthetic-perplexity-key"
SIGNATURE = "dGhvdWdodA=="
BOX = [100, 50, 350, 330]
EDITED = [100, 50, 300, 300]


def _completed(*items):
    return {"type": "response.completed", "response": {"status": "completed", "output": items}}


def _message(text):
    return {"type": "message", "content": [{"type": "output_text", "text": text}]}


@asynccontextmanager
async def _endpoint(monkeypatch, replies, *, stalled=False):
    requests = []
    disconnected = asyncio.Event()

    async def handle(reader, writer):
        try:
            request = await reader.readline()
            headers = {}
            while (line := await reader.readline()).strip():
                name, value = line.decode("ascii").split(":", 1)
                headers[name.lower()] = value.strip()
            body = json.loads(await reader.readexactly(int(headers["content-length"])))
            reply = replies[len(requests)]
            requests.append((request, headers["authorization"], body))
            stream = "".join(f"data: {json.dumps(event)}\n\n" for event in reply).encode("utf-8")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n" + stream)
            await writer.drain()
            if stalled:
                await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            disconnected.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(perplexity_provider, "ENDPOINT", f"http://127.0.0.1:{port}/v1/agent")
    monkeypatch.setenv("BADSHOP_PERPLEXITY_TEST_KEY", KEY)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    async with server:
        yield requests, disconnected


async def _select(client, model=MODEL):
    profile = await client.call("providers.save", profile={
        "kind": "api", "label": "Perplexity", "model": f"perplexity_agent/{model}",
        "api_key_env": "BADSHOP_PERPLEXITY_TEST_KEY",
    })
    result = await client.call("providers.test", profile_id=profile["id"])
    assert result["status"] == "ready" and not result["probed"]
    await client.call("providers.select", profile_id=profile["id"])


@pytest.mark.parametrize(("model", "decision"), [
    (MODEL, "edit"),
    ("google/gemini-3.8-flash", "reject"),
    ("anthropic/claude-sonnet-5-5", "edit"),
])
def test_perplexity_image_approval_and_tool_result(env, monkeypatch, model, decision):
    async def body(app):
        client = Client(app)
        aid = await imported(client)
        source = app.session.artifacts.image(aid)
        call = {"type": "function_call", "call_id": "call_cutout", "name": "cutout",
                "arguments": json.dumps({"image": aid, "box": BOX, "no_ai": True}),
                "thought_signature": SIGNATURE, "status": "completed"}
        replies = [
            [{"type": "response.output_text.delta", "delta": "I can crop that."},
             _completed(_message("I can crop that."), call)],
            [_completed(_message("The tool decision was recorded."))],
        ]
        async with _endpoint(monkeypatch, replies) as (requests, _):
            await _select(client, model)
            assert not requests
            await client.call("chat.send", text="Crop this image.", attachments=[aid])
            step_id = await client.waiting(lambda step: step["tool"] == "cutout")
            assert app.session.step(step_id).status == "proposed"
            assert not app.session.step(step_id).outputs and len(requests) == 1
            request, auth, initial = requests[0]
            assert request == b"POST /v1/agent HTTP/1.1\r\n" and auth == f"Bearer {KEY}"
            assert initial["model"] == model and initial["stream"] and not initial["store"]
            if model.startswith("anthropic/"):
                assert initial["max_output_tokens"] == 8192
            assert initial["tools"] and {tool["type"] for tool in initial["tools"]} == {"function"}
            assert any(tool["name"] == "cutout" and "parameters" in tool for tool in initial["tools"])
            assert await client.event("message.delta") == {"text": "I can crop that."}
            image_url, = [part["image_url"] for item in initial["input"]
                          if isinstance(item.get("content"), list)
                          for part in item["content"] if part["type"] == "input_image"]
            prefix, encoded = image_url.split(",", 1)
            assert prefix == "data:image/png;base64"
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as attached:
                assert attached.size == source.size and attached.convert("RGBA").tobytes() == source.convert("RGBA").tobytes()
            if decision == "edit":
                await client.call("approval.respond", step_id=step_id, decision="edit",
                                  params={"image": aid, "box": EDITED, "no_ai": True})
            else:
                await client.call("approval.respond", step_id=step_id, decision="reject", note="Leave it intact")
            assert await client.event("turn.finished") == {"reason": "done"}
            await idle(client)
            sent = requests[1][2]["input"]
            replayed, result = sent[-2:]
            assert replayed == {key: value for key, value in call.items() if key != "status"}
            assert result["type"] == "function_call_output" and result["call_id"] == call["call_id"]
            assert result["name"] == "cutout" and result["thought_signature"] == SIGNATURE
            step = app.session.step(step_id)
            if decision == "edit":
                assert step.status == "done" and step.params["box"] == EDITED
                assert "user edited the parameters" in result["output"]
                output, = step.outputs
                with app.session.artifacts.image(output) as cropped:
                    assert cropped.size == (200, 250)
                    assert cropped.convert("RGB").tobytes() == source.crop(EDITED).convert("RGB").tobytes()
            else:
                assert step.status == "rejected" and not step.outputs
                assert result["output"] == "rejected by user: Leave it intact"
        source.close()
        path = env / "perplexity.badshop"
        await client.call("session.save_as", path=str(path))
        reopened = project.open_project(path)
        assert reopened.data.transcript == app.session.data.transcript
        call, = [call for message in build_messages(reopened) for call in message.get("tool_calls", [])]
        assert "thought_signature" not in call
        if decision == "edit":
            assert hashlib.sha256(reopened.artifacts.data(output)).hexdigest() == output

    run(body, Settings(approval_mode="ask_all"))


@pytest.mark.parametrize("failure", ["truncated", "stopped", "missing-call-status"])
def test_perplexity_incomplete_stream_cannot_run_a_tool(env, monkeypatch, failure):
    async def body(app):
        client = Client(app)
        aid = await imported(client)
        call = {
            "type": "function_call", "call_id": "partial", "name": "cutout",
            "arguments": json.dumps({"image": aid, "box": BOX, "no_ai": True}),
        }
        events = [{"type": "response.output_item.done", "item": call},
                  {"type": "response.output_text.delta", "delta": "Working"}]
        if failure == "missing-call-status":
            events.append(_completed(call))
        stalled = failure == "stopped"
        async with _endpoint(monkeypatch, [events], stalled=stalled) as (_, disconnected):
            await _select(client)
            await client.call("chat.send", text="Crop this image.", attachments=[aid])
            await client.event("message.delta")
            if stalled:
                await client.call("chat.stop")
            finished = await client.event("turn.finished")
            assert finished["reason"] == ("stopped" if stalled else "provider_error")
            await asyncio.wait_for(disconnected.wait(), 5)
            assert not app.session.data.steps
            assert not (await idle(client))["pending_approvals"]

    run(body, Settings(approval_mode="auto"))
