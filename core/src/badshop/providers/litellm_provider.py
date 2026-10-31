"""Streaming chat/vision through LiteLLM's OpenAI-format API.

Only completions are exposed here: image generation is never a badshop operation.
Provider exception bodies can contain keys, request images, and endpoint credentials;
the application receives a fixed, actionable message instead of those bodies.
"""

import asyncio
import copy
import importlib
import inspect
import math
import os
import sys
from collections.abc import Callable
from typing import Any

from badshop.agent.provider import ProviderError, Reply, ToolCallRequest


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


class LiteLLMProvider:
    def __init__(self, model: str, *, api_base: str | None = None, api_key: str | None = None,
                 actor: str = "agent:litellm", capability_overrides: dict[str, bool] | None = None,
                 timeout_s: float = 120):
        self.model, self.api_base, self._api_key = model, api_base, api_key
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

        This slice requires native tool calls; silently dropping tools would leave an
        apparently working art director unable to create anything.
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
        if not caps["tool_calls"]:
            raise ProviderError("this model has no confirmed native tool support; choose a tool-capable model "
                                "or enable its tool_calls override. JSON-mode fallback is not implemented yet")
        self._capabilities = caps
        return dict(caps)

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply:
        if self._capabilities is None:
            await asyncio.to_thread(self.check_capabilities)
        sdk = _load_sdk()
        kwargs = {"model": self.model, "messages": copy.deepcopy(messages),
                  "stream": True, "timeout": self.timeout_s, "num_retries": 0}
        if tools:
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
                    return Reply(text=text)
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
