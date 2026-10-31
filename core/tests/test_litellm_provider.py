import asyncio
import base64
import copy
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from PIL import Image

from badshop.agent.provider import ProviderError
from badshop.providers import litellm_provider as adapter
from badshop.providers.litellm_provider import LiteLLMProvider


def chunk(content=None, calls=None, finish=None):
    return {"choices": [{"index": 0, "delta": {"content": content, "tool_calls": calls},
                         "finish_reason": finish}]}


def call(index, id=None, name=None, args=""):
    return {"index": index, "id": id, "function": {"name": name, "arguments": args}}


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for entry in self.chunks:
            await asyncio.sleep(0)
            if isinstance(entry, Exception):
                raise entry
            yield copy.deepcopy(entry)

    async def aclose(self):
        self.closed = True


class SDK:
    """Offline SDK stand-in; a separate contract test uses LiteLLM's actual builder."""

    def __init__(self, chunks):
        self.stream = Stream(chunks)
        self.requests = []
        self.vision = True
        self.tools = True

    def supports_vision(self, model):
        return self.vision

    def supports_function_calling(self, model):
        return self.tools

    async def acompletion(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        kwargs["messages"].append({"role": "assistant", "content": "SDK mutation"})
        return self.stream

    def stream_chunk_builder(self, chunks, messages):
        calls = {}
        content = ""
        for chunk in chunks:
            for choice in chunk["choices"]:
                delta = choice["delta"]
                content += delta.get("content") or ""
                for call in delta.get("tool_calls") or []:
                    target = calls.setdefault(call["index"], {"id": "", "function": {"name": "", "arguments": ""}})
                    target["id"] += call.get("id") or ""
                    for key in ("name", "arguments"):
                        target["function"][key] += call["function"].get(key) or ""
        return {"choices": [{"message": {"content": content, "tool_calls": list(calls.values())}}]}


def use_sdk(monkeypatch, chunks):
    sdk = SDK(chunks)
    monkeypatch.setattr(adapter, "_load_sdk", lambda: sdk)
    return sdk


def complete(provider, messages=None, tools=None):
    deltas = []
    result = asyncio.run(provider.complete(messages or [], tools or [], deltas.append))
    return result, deltas


def test_streamed_text_parallel_calls_and_exact_request(monkeypatch):
    sdk = use_sdk(monkeypatch, [chunk("Look ", [call(0, "c1", "find", '{"image":'),
                                               call(1, "c2", "view", '{"image":"aabbccdd"')]),
                               chunk("here", [call(0, args='"aabbccdd"}'), call(1, args='}')]),
                               chunk(finish="tool_calls"), {"choices": []}])
    provider = LiteLLMProvider("openai/local-vision", api_base="http://localhost:1234/v1", api_key="secret",
                              actor="agent:my-local")
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]
    tools = [{"type": "function", "function": {"name": "find"}}]
    snapshot = copy.deepcopy((messages, tools))
    reply, deltas = complete(provider, messages, tools)
    assert reply.text == "Look here" and deltas == ["Look ", "here"]
    assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [
        ("c1", "find", '{"image":"aabbccdd"}'), ("c2", "view", '{"image":"aabbccdd"}')]
    assert (messages, tools) == snapshot
    assert provider.actor == "agent:my-local"
    assert sdk.requests[0]["api_key"] == "secret"
    assert sdk.requests[0]["api_base"] == "http://localhost:1234/v1"
    assert sdk.requests[0]["tool_choice"] == "auto" and sdk.requests[0]["num_retries"] == 0
    assert sdk.stream.closed


def test_text_only_reply_and_no_key_are_supported(monkeypatch):
    sdk = use_sdk(monkeypatch, [chunk("Done.", finish="stop")])
    reply, _ = complete(LiteLLMProvider("ollama_chat/vision"))
    assert reply.text == "Done." and not reply.tool_calls
    assert "api_key" not in sdk.requests[0] and "api_base" not in sdk.requests[0]
    assert "tools" not in sdk.requests[0] and "tool_choice" not in sdk.requests[0]


def test_custom_endpoint_does_not_inherit_a_cloud_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-cloud-key")
    sdk = use_sdk(monkeypatch, [chunk("Done.", finish="stop")])
    complete(LiteLLMProvider("openai/local", api_base="http://localhost:1234/v1"))
    assert sdk.requests[0]["api_key"] == "badshop-local"


@pytest.mark.parametrize("vision,tools,expected", [(False, True, "image support"), (True, False, "tool support")])
def test_capabilities_refuse_unsupported_models(monkeypatch, vision, tools, expected):
    sdk = use_sdk(monkeypatch, [])
    sdk.vision, sdk.tools = vision, tools
    with pytest.raises(ProviderError, match=expected):
        complete(LiteLLMProvider("openai/unknown"))
    assert not sdk.requests


def test_custom_model_overrides_and_defensive_capability_copy(monkeypatch):
    sdk = use_sdk(monkeypatch, [])
    sdk.vision = sdk.tools = False
    p = LiteLLMProvider("openai/custom", capability_overrides={"vision": True, "tool_calls": True})
    caps = p.check_capabilities()
    assert caps == {"vision": True, "tool_calls": True}
    caps["vision"] = False
    assert p._capabilities["vision"]


@pytest.mark.parametrize("overrides", [{"typo": True}, {"vision": "yes"}, {"tool_calls": 1}])
def test_invalid_overrides(overrides):
    with pytest.raises(ProviderError, match="overrides"):
        LiteLLMProvider("openai/test", capability_overrides=overrides)


@pytest.mark.parametrize("chunks,expected", [([], "complete reply"), ([chunk("partial")], "complete reply"),
                                            ([chunk(finish="length")], "cut off")])
def test_incomplete_streams_never_produce_a_reply(monkeypatch, chunks, expected):
    sdk = use_sdk(monkeypatch, chunks)
    with pytest.raises(ProviderError, match=expected):
        complete(LiteLLMProvider("openai/test"))
    assert sdk.stream.closed


def test_content_filter_is_a_model_reply_without_tool_calls(monkeypatch):
    sdk = use_sdk(monkeypatch, [chunk("I cannot help.", [call(0, "a", "find", "{unfinished")],
                                    finish="content_filter")])
    reply, deltas = complete(LiteLLMProvider("openai/test"))
    assert reply.text == "I cannot help." and not reply.tool_calls
    assert deltas == ["I cannot help."] and sdk.stream.closed


def test_refusal_delta_is_a_model_reply(monkeypatch):
    entry = chunk(finish="stop")
    entry["choices"][0]["delta"]["refusal"] = "I cannot help with that."
    use_sdk(monkeypatch, [entry])
    reply, deltas = complete(LiteLLMProvider("openai/test"))
    assert reply.text == "I cannot help with that." and deltas == [reply.text]
    assert not reply.tool_calls


def test_bad_json_is_passed_to_agent_validation(monkeypatch):
    use_sdk(monkeypatch, [chunk(calls=[call(0, "a", "find", "{oops")], finish="tool_calls")])
    reply, _ = complete(LiteLLMProvider("openai/test"))
    assert reply.tool_calls[0].arguments == "{oops"


def test_lost_calls_in_builder_are_detected(monkeypatch):
    sdk = use_sdk(monkeypatch, [chunk(calls=[call(0, "a", "find", "{}")], finish="tool_calls")])
    sdk.stream_chunk_builder = lambda *a, **k: {"choices": [{"message": {"content": "", "tool_calls": []}}]}
    with pytest.raises(ProviderError, match="could not be rebuilt"):
        complete(LiteLLMProvider("openai/test"))
    assert sdk.stream.closed


@pytest.mark.parametrize("calls", [[call(0, "a", None, "{}")], [call(0, None, "find", "{}")],
                                  [call(0, "a", "find", "{}"), call(1, "a", "view", "{}")]])
def test_malformed_or_duplicate_calls_fail_before_execution(monkeypatch, calls):
    use_sdk(monkeypatch, [chunk(calls=calls, finish="tool_calls")])
    with pytest.raises(ProviderError, match="incomplete tool call"):
        complete(LiteLLMProvider("openai/test"))


@pytest.mark.parametrize("kind,status,match", [("AuthenticationError", 401, "authentication"),
                                              ("Unknown", 403, "access"), ("RateLimitError", 429, "quota"),
                                              ("ContextWindowExceededError", 400, "context window"),
                                              ("Timeout", None, "timed out"),
                                              ("APIConnectionError", None, "can't reach"),
                                              ("BadRequestError", 400, "refused"), ("Unknown", None, "failed")])
def test_sdk_errors_never_expose_body_or_credentials(monkeypatch, kind, status, match):
    error = type(kind, (Exception,), {"status_code": status})("secret-key data:image/png;base64,private-photo")
    sdk = use_sdk(monkeypatch, [chunk("partial"), error])
    with pytest.raises(ProviderError, match=match) as caught:
        complete(LiteLLMProvider("openai/test", api_key="secret-key"))
    assert "secret" not in str(caught.value) and "private-photo" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert sdk.stream.closed


def test_cancel_closes_stream(monkeypatch):
    sdk = use_sdk(monkeypatch, [])

    async def main():
        waiting = asyncio.Event()

        class Waiting(Stream):
            async def __aiter__(self):
                waiting.set()
                await asyncio.Event().wait()
                yield chunk()

        sdk.stream = Waiting([])
        task = asyncio.create_task(LiteLLMProvider("openai/test").complete([], [], lambda _: None))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert sdk.stream.closed

    asyncio.run(main())


def test_total_deadline_closes_a_stalled_stream(monkeypatch):
    sdk = use_sdk(monkeypatch, [])

    class Waiting(Stream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield chunk()

    sdk.stream = Waiting([])
    with pytest.raises(ProviderError, match="timed out"):
        complete(LiteLLMProvider("openai/test", timeout_s=0.01))
    assert sdk.stream.closed


def test_real_litellm_builder_keeps_fragmented_tool_calls(monkeypatch):
    # Contract test: no network/model/key needed, but uses the actual locked SDK.
    sdk = adapter._load_sdk()
    raw = [chunk("Look", [call(0, "c1", "find", '{"image":')]),
           chunk(calls=[call(0, args='"abcd1234"}')]), chunk(finish="tool_calls")]
    chunks = [sdk.ModelResponse(model="test", stream=True, **part) for part in raw]
    stream = Stream(chunks)

    async def request(**kwargs):
        return stream

    monkeypatch.setattr(adapter, "_load_sdk", lambda: SimpleNamespace(
        acompletion=request, stream_chunk_builder=sdk.stream_chunk_builder))
    provider = LiteLLMProvider("openai/test", capability_overrides={"vision": True, "tool_calls": True})
    reply, deltas = complete(provider)
    assert reply.text == "Look" and deltas == ["Look"]
    assert reply.tool_calls[0].arguments == '{"image":"abcd1234"}'
    assert stream.closed


def test_real_litellm_openai_compatible_sse_with_images(monkeypatch):
    """Exercise the real async HTTP adapter against a local, deterministic provider."""
    adapter._load_sdk()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append((self.path, self.headers.get("Authorization"),
                             json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for part in [chunk("I see it.", [call(0, "local_call", "view", '{"image":')]),
                         chunk(calls=[call(0, args='"abcd1234"}')]), chunk(finish="tool_calls")]:
                part.update(id="chatcmpl-local", object="chat.completion.chunk", created=1, model="local-vision")
                self.wfile.write(f"data: {json.dumps(part)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    png = io.BytesIO()
    with Image.new("RGB", (16, 16), "red") as image:
        image.save(png, "PNG")
    data_url = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
    messages = [{"role": "user", "content": [{"type": "text", "text": "Inspect this."},
                                               {"type": "image_url", "image_url": {"url": data_url}}]}]
    tools = [{"type": "function", "function": {"name": "view", "description": "View an image",
             "parameters": {"type": "object", "properties": {"image": {"type": "string"}},
                            "required": ["image"]}}}]
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-local-server")
    try:
        provider = LiteLLMProvider("openai/local-vision", api_base=f"http://127.0.0.1:{server.server_port}/v1",
                                  capability_overrides={"vision": True, "tool_calls": True}, timeout_s=10)
        async def request():
            deltas = []
            try:
                return await provider.complete(messages, tools, deltas.append), deltas
            finally:
                await adapter.close_clients()
        reply, deltas = asyncio.run(request())
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
    assert reply.text == "I see it." and "".join(deltas) == reply.text
    assert reply.tool_calls[0].id == "local_call"
    assert reply.tool_calls[0].arguments == '{"image":"abcd1234"}'
    path, authorization, request = requests[0]
    assert path == "/v1/chat/completions" and authorization == "Bearer badshop-local"
    assert request["messages"][0]["content"][1]["image_url"]["url"] == data_url
    assert request["tools"][0]["function"]["name"] == "view"


def test_real_ollama_chat_transform_preserves_images():
    adapter._load_sdk()
    from litellm.llms.ollama.chat.transformation import OllamaChatConfig

    image_data = base64.b64encode(b"image-bytes").decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Inspect this."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
    ]}]
    data = OllamaChatConfig().transform_request("local-vision", messages, {"stream": True}, {}, {})
    assert data["messages"][0]["images"] == [image_data]
    assert data["messages"][0]["content"] == "Inspect this."
