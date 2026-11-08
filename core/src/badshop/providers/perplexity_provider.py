"""Adapt BadShop's chat transcript to Perplexity's Agent API Responses format."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import httpx

from badshop.agent.provider import ProviderError, Reply, ToolCallRequest
from badshop.providers.litellm_provider import LiteLLMProvider, safe_error

MODEL_PREFIX = "perplexity_agent/"
ENDPOINT = "https://api.perplexity.ai/v1/agent"


def _inputs(messages: list[dict]) -> list[dict]:
    inputs = []
    calls: dict[str, dict] = {}
    for message in messages:
        role, content = message["role"], message.get("content")
        if role == "tool":
            call_id = message["tool_call_id"]
            call = calls[call_id]
            result = {"type": "function_call_output", "call_id": call_id, "name": call["name"], "output": content}
            if call.get("thought_signature"):
                result["thought_signature"] = call["thought_signature"]
            inputs.append(result)
            continue
        if isinstance(content, list):
            content = [
                {"type": "input_image", "image_url": part["image_url"]["url"]}
                if part["type"] == "image_url" else {"type": "input_text", "text": part["text"]}
                for part in content
            ]
        if content is not None:
            inputs.append({"type": "message", "role": role, "content": content})
        for call in message.get("tool_calls") or []:
            item = {"type": "function_call", "call_id": call["id"], **call["function"]}
            if call.get("thought_signature"):
                item["thought_signature"] = call["thought_signature"]
            inputs.append(item)
            calls[call["id"]] = item
    return inputs


async def _events(response: httpx.Response) -> AsyncIterator[dict]:
    data: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            payload = "\n".join(data)
            data.clear()
            if payload == "[DONE]":
                return
            event = json.loads(payload)
            if not isinstance(event, dict):
                raise ProviderError("Perplexity returned an invalid stream event")
            yield event


def _reply(response: dict) -> Reply:
    if response.get("status") != "completed" or not isinstance(response.get("output"), list):
        raise ProviderError("Perplexity did not complete its reply. No tools ran.")
    text = []
    calls = []
    ids = set()
    refused = False
    for item in response["output"]:
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    refused = True
                    text.append(part.get("refusal") or "The model declined this request.")
                elif part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    text.append(part["text"])
        elif item.get("type") == "function_call":
            call_id, name, args = item.get("call_id"), item.get("name"), item.get("arguments")
            signature = item.get("thought_signature")
            if (item.get("status") != "completed"
                    or not isinstance(call_id, str) or not 1 <= len(call_id) <= 1024 or call_id in ids
                    or not isinstance(name, str) or not 1 <= len(name) <= 128
                    or not isinstance(args, str)
                    or (signature is not None and (not isinstance(signature, str) or len(signature) > 65536))):
                raise ProviderError("Perplexity returned an incomplete or invalid tool call. No tools ran.")
            ids.add(call_id)
            calls.append(ToolCallRequest(call_id, name, args, signature))
    if not text and not calls:
        raise ProviderError("Perplexity returned an empty reply")
    return Reply(text="".join(text), tool_calls=[] if refused else calls)


class PerplexityProvider(LiteLLMProvider):
    """Use LiteLLM's local capability catalog, with no SDK calls to the Chat endpoint."""

    thought_signatures = True

    def check_capabilities(self, *, catalog_model: str | None = None) -> dict[str, bool]:
        if self.api_base:
            raise ProviderError("Perplexity uses its Agent API URL. Clear the custom API base.")
        if not self._api_key:
            raise ProviderError("Add a Perplexity API key or select an environment variable that contains it.")
        if self.model.startswith("google/"):
            catalog_model = "gemini/" + self.model.removeprefix("google/")
        capabilities = super().check_capabilities(catalog_model=catalog_model)
        if not capabilities["tool_calls"]:
            raise ProviderError("Choose a Perplexity Agent API model with native function calling.")
        return capabilities

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply:
        if self._capabilities is None or not self._capabilities["tool_calls"]:
            await asyncio.to_thread(self.check_capabilities)
        body = {
            "model": self.model,
            "input": _inputs(messages),
            "tools": [{"type": "function", **tool["function"], "strict": False} for tool in tools],
            "stream": True,
            "store": False,
        }
        if self.model.startswith("anthropic/"):
            body["max_output_tokens"] = 8192  # required by the Agent API for Anthropic models
        streamed = False
        try:
            async with asyncio.timeout(self.timeout_s), httpx.AsyncClient(timeout=self.timeout_s) as client:
                async with client.stream("POST", ENDPOINT, json=body,
                                         headers={"Authorization": f"Bearer {self._api_key}",
                                                  "Accept": "text/event-stream"}) as response:
                    response.raise_for_status()
                    async for event in _events(response):
                        kind = event.get("type")
                        if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                            streamed = True
                            on_delta(event["delta"])
                        elif kind == "response.completed":
                            reply = _reply(event.get("response") or {})
                            if reply.text and not streamed:
                                on_delta(reply.text)
                            return reply
                        elif kind in ("error", "response.failed", "response.incomplete"):
                            raise ProviderError("Perplexity did not complete its reply. No tools ran.")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(safe_error(exc)) from None
        raise ProviderError("Perplexity's stream ended before a complete reply. No tools ran.")
