"""Streaming chat/vision through LiteLLM's OpenAI-format API.

Only completions are exposed here: image generation is never a badshop operation.
Provider exception bodies can contain keys, request images, and endpoint credentials;
the application receives a fixed, actionable message instead of those bodies.
"""

import asyncio
import copy
import importlib
import inspect
import json
import uuid
import math
import os
import sys
from collections.abc import Callable
from typing import Any

from badshop.agent.provider import ProviderError, Reply, ToolCallRequest
from badshop.diagnostics import register_secret


async def close_clients() -> None:
    """Close SDK connection pools at application shutdown, without importing it."""
    sdk = sys.modules.get("litellm")
    if sdk is not None:
        await sdk.close_litellm_async_clients()


def _load_sdk():
    # Capability checks should work offline from the installed package's catalogue.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    try:
        sdk = importlib.import_module("litellm")
    except ImportError:
        raise ProviderError("LiteLLM is not installed; install badshop's provider dependencies") from None
    sdk.suppress_debug_info = True
    sdk.turn_off_message_logging = True
    return sdk


def _get(obj: Any, name: str, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _safe_error(exc: Exception) -> str:
    """Class/status only; never interpolate an SDK exception or its response body."""
    kind = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if kind == "AuthenticationError" or status == 401:
        return "model authentication failed; check the provider's API key"
    if kind == "PermissionDeniedError" or status == 403:
        return "the provider refused access; check the key's permissions and model access"
    if kind == "NotFoundError" or status == 404:
        return "the model or endpoint is unavailable; check the model name and API base, or choose another model"
    if kind == "RateLimitError" or status == 429:
        return "the model's rate limit or quota was reached; wait or check your provider account"
    if kind == "ContextWindowExceededError":
        return "the conversation exceeds the model's context window; start a new session or choose a larger model"
    if isinstance(exc, TimeoutError) or kind in ("Timeout", "APITimeoutError"):
        return "the model request timed out; check the connection and try again"
    if kind in ("APIConnectionError", "ServiceUnavailableError"):
        return "can't reach the model provider; check its endpoint and your connection"
    if kind in ("BadRequestError", "UnsupportedParamsError") or status == 400:
        return "the provider refused the request; check the model's image and tool support"
    return "the model request failed; check the provider settings and try again"


async def _close_stream(stream) -> None:
    """Release the HTTP stream on success, errors, and Stop (including a repeated Stop)."""
    close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
    if close is None:
        return

    async def close_it():
        try:
            async with asyncio.timeout(5):
                result = close()
                if inspect.isawaitable(result):
                    await result
        except Exception:
            pass  # a cleanup failure must not replace the useful completion/error

    task = asyncio.create_task(close_it())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


_JSON_INSTRUCTION = """For this model, badshop uses JSON-mode tool calls. Return exactly one JSON object:
{"text": "your explanation or final answer", "tool_calls": [{"name": "tool_name", "arguments": {}}]}.
Use an empty tool_calls array for a final answer. Do not use markdown fences. Arguments must be a JSON
object with the tool's declared parameters. Request only listed tools. Tool results and previous calls
are shown as JSON in the conversation. A rejected call was not run; respect the user's decision.
The application validates each call, asks for approval when needed, and executes it. Never claim a
requested call has already run. All existing image and pixel safety instructions still apply.
Available tools (JSON schemas):
"""


def _json_messages(messages: list[dict], tools: list[dict]) -> list[dict]:
    """Remove native tool roles while preserving every multimodal content block."""
    result = [{"role": "system", "content": _JSON_INSTRUCTION + json.dumps(tools)}]
    for entry in copy.deepcopy(messages):
        if entry.get("role") == "tool":
            result.append({"role": "user", "content": json.dumps({
                "tool_result": {"id": entry.get("tool_call_id"), "content": entry.get("content")}
            })})
        elif entry.get("tool_calls"):
            calls = [{"name": c.get("function", {}).get("name"),
                      "arguments": c.get("function", {}).get("arguments"), "id": c.get("id")}
                     for c in entry.pop("tool_calls")]
            content = entry.get("content")
            envelope = json.dumps({"text": content if isinstance(content, str) else "", "tool_calls": calls})
            # Native assistant messages normally contain text only, but preserve image blocks if present.
            entry["content"] = ([{"type": "text", "text": envelope}, *content]
                                if isinstance(content, list) else envelope)
            result.append(entry)
        else:
            entry.pop("tool_calls", None)
            result.append(entry)
    return result


def _json_reply(text: str) -> Reply:
    """A malformed envelope produces no deltas and no executable call fragments."""
    try:
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (not isinstance(value, dict) or set(value) - {"text", "tool_calls"}
                or not isinstance(value.get("text", ""), str)
                or not isinstance(value.get("tool_calls", []), list)):
            raise ValueError
        calls = []
        for call in value.get("tool_calls", []):
            if (not isinstance(call, dict) or set(call) != {"name", "arguments"}
                    or not isinstance(call["name"], str) or not call["name"]
                    or not isinstance(call["arguments"], (dict, str))):
                raise ValueError
            calls.append(ToolCallRequest(id="json_" + uuid.uuid4().hex,
                                         name=call["name"], arguments=call["arguments"]))
        return Reply(text=value.get("text", ""), tool_calls=calls)
    except (ValueError, RecursionError, TypeError):
        raise ProviderError("the model returned invalid JSON-mode tool data; no calls were run. "
                            "Try again or choose a model with native tool support") from None


class LiteLLMProvider:
    def __init__(self, model: str, *, api_base: str | None = None, api_key: str | None = None,
                 actor: str = "agent:litellm", capability_overrides: dict[str, bool] | None = None,
                 timeout_s: float = 120):
        self.model, self.api_base, self._api_key = model, api_base, api_key
        if api_key:
            register_secret(api_key)
        self.warnings: list[str] = []
        self.actor = actor
        self.capability_overrides = dict(capability_overrides or {})
        if (set(self.capability_overrides) - {"vision", "tool_calls"}
                or any(type(v) is not bool for v in self.capability_overrides.values())):
            raise ProviderError("capability overrides must be boolean vision and tool_calls values")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ProviderError("the model request timeout must be a positive number")
        self.timeout_s = timeout_s
        self._capabilities: dict[str, bool] | None = None

    def check_capabilities(self) -> dict[str, bool]:
        """Check local metadata, with explicit overrides for custom/local models.

        Models without native tools use a strict JSON envelope. Calls still return to
        the ordinary agent validation/approval loop, never to an SDK executor.
        """
        sdk = _load_sdk()
        caps = {}
        for key, name in (("vision", "supports_vision"), ("tool_calls", "supports_function_calling")):
            if key in self.capability_overrides:
                caps[key] = self.capability_overrides[key]
            else:
                try:
                    caps[key] = bool(getattr(sdk, name)(model=self.model))
                except Exception:
                    caps[key] = False  # unknown metadata needs a deliberate profile override
        if not caps["vision"]:
            raise ProviderError("this model has no confirmed image support; choose a vision model or enable "
                                "the vision override for a custom model that supports images")
        self.warnings = [] if caps["tool_calls"] else [
            "This model has no confirmed native tool support. JSON-mode tool fallback is active; "
            "tool selection and placement may be poor. A model with native tools is recommended."
        ]
        self._capabilities = caps
        return dict(caps)

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply:
        if self._capabilities is None:
            await asyncio.to_thread(self.check_capabilities)
        sdk = _load_sdk()
        fallback = not self._capabilities["tool_calls"]
        request_messages = _json_messages(messages, tools) if fallback else copy.deepcopy(messages)
        kwargs = {"model": self.model, "messages": request_messages,
                  "stream": True, "timeout": self.timeout_s, "num_retries": 0}
        if fallback:
            kwargs["response_format"] = {"type": "json_object"}
        elif tools:
            # The locked LiteLLM imports its optional MCP gateway for any tool
            # list unless bypassed. These are function definitions only; badshop's
            # approval/session loop must remain the sole tool executor.
            kwargs.update(tools=copy.deepcopy(tools), tool_choice="auto", _skip_mcp_handler=True)
        if self.api_base is not None:
            kwargs["api_base"] = self.api_base
        if self._api_key is not None:
            kwargs["api_key"] = self._api_key
        elif self.api_base is not None:
            # A local/custom endpoint must not inherit a cloud credential from the
            # SDK's environment fallback. Authenticated custom profiles resolve
            # their key explicitly before constructing this adapter.
            kwargs["api_key"] = "badshop-local"
        stream = None
        try:
            # This also bounds a provider that keeps trickling chunks forever.
            async with asyncio.timeout(self.timeout_s):
                stream = await sdk.acompletion(**kwargs)
                chunks = []
                seen_calls: set[int] = set()
                finished = False
                refused = False
                text_parts: list[str] = []
                refusal_parts: list[str] = []
                async for chunk in stream:
                    chunks.append(chunk)
                    for choice in _get(chunk, "choices", []) or []:
                        if _get(choice, "index", 0) != 0:
                            continue
                        reason = _get(choice, "finish_reason")
                        if reason == "length":
                            raise ProviderError("the provider cut off its reply; no tool calls from it were run")
                        refused |= reason == "content_filter"
                        finished |= reason is not None
                        delta = _get(choice, "delta", {})
                        content = _get(delta, "content")
                        if isinstance(content, str) and content:
                            text_parts.append(content)
                            if not fallback:
                                on_delta(content)
                        refusal = _get(delta, "refusal")
                        if isinstance(refusal, str) and refusal:
                            refused = True
                            refusal_parts.append(refusal)
                            on_delta(refusal)
                        for call in _get(delta, "tool_calls", []) or []:
                            seen_calls.add(_get(call, "index", 0))
                if not chunks or not finished:
                    raise ProviderError("the model stream ended before a complete reply; try again")
                if refused:
                    # Refusals are model replies, not retryable transport failures.
                    # Never execute a tool fragment from a refused completion.
                    text = "".join(refusal_parts or text_parts)
                    if not text:
                        text = "The model declined this request."
                        on_delta(text)
                    if fallback and not refusal_parts:
                        on_delta(text)
                    return Reply(text=text)
                if fallback:
                    reply = _json_reply("".join(text_parts))
                    if reply.text:
                        on_delta(reply.text)
                    return reply
                rebuilt = sdk.stream_chunk_builder(chunks, messages=kwargs["messages"])
                choices = _get(rebuilt, "choices", []) or []
                if not choices:
                    raise ProviderError("the model returned an empty reply; try again")
                message = _get(choices[0], "message", {})
                text = _get(message, "content") or ""
                if not isinstance(text, str):
                    raise ProviderError("the model returned unsupported content; choose a chat model")
                calls = []
                ids = set()
                for call in _get(message, "tool_calls", []) or []:
                    fn = _get(call, "function", {})
                    call_id, name = _get(call, "id"), _get(fn, "name")
                    args = _get(fn, "arguments")
                    if (not isinstance(call_id, str) or not call_id or call_id in ids
                            or not isinstance(name, str) or not name or not isinstance(args, (str, dict))):
                        raise ProviderError("the model returned an incomplete tool call; try again")
                    ids.add(call_id)
                    # JSON validation belongs to the agent loop: it returns errors to the model.
                    calls.append(ToolCallRequest(id=call_id, name=name, arguments=args))
                if len(calls) != len(seen_calls):
                    raise ProviderError("the provider's streamed tool calls could not be rebuilt; try another model")
                return Reply(text=text, tool_calls=calls)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(_safe_error(exc)) from None
        finally:
            if stream is not None:
                await _close_stream(stream)
