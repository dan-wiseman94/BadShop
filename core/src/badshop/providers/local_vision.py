"""Inference and face selection for the optional on-device assistant."""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from copy import deepcopy

import httpx

from badshop.agent.provider import ProviderError, Reply, ToolCallRequest

PROFILE_ID = "badshop-on-device"
LABEL = "On-device AI"
TOOLS = frozenset({"text", "deepfry", "filter", "censor"})
LASER = re.compile(r"\blaser[\s-]+eyes\b", re.IGNORECASE)
ARTIFACT = re.compile(r"Artifact ID: ([0-9a-f]{64})$")
NOT_APPLIED = ("error:", "rejected", "not run:")
PROMPT = """You edit photos in BadShop with the supplied tools. Make one requested edit, then stop.
Use the source image's artifact ID exactly as shown, without its label or brackets.
Ask the user when the target is unclear or no photo is available.
If the edit is outside your tools, explain that and suggest using BadShop's tools directly."""


class LocalVisionProvider:
    actor = f"agent:{PROFILE_ID}"
    full_image_ids = True
    warnings: list[str] = []

    def __init__(self, endpoint: Callable[[], Awaitable[tuple[str, str]]],
                 available: Callable[[], bool]) -> None:
        self._endpoint = endpoint
        self._available = available

    def check_capabilities(self) -> dict[str, bool]:
        if not self._available():
            raise ProviderError("Set up On-device AI in Settings → Assets before using it.")
        return {"vision": True, "tool_calls": True}

    async def complete(self, messages: list[dict], tools: list[dict], on_delta: Callable[[str], None]) -> Reply:
        last_user = max((i for i, message in enumerate(messages) if message["role"] == "user"), default=0)
        user = messages[last_user]["content"]
        text = user[0].get("text", "") if isinstance(user, list) and user else user
        turn = messages[last_user + 1:]
        if tools and isinstance(text, str) and LASER.search(text):
            return await self._laser(text, user, turn)
        result = next((item["content"] for item in reversed(turn) if item["role"] == "tool"), None)
        # Invalid image references never create a step. Give the model its validation result
        # so the agent's existing bounded repair loop can correct the reference itself.
        if tools and isinstance(result, str) and not result.startswith("error: no such artifact:"):
            if result.startswith(NOT_APPLIED):
                return Reply(f"The edit wasn’t applied.\n\n{result}")
            return Reply("Edit applied.")
        async with httpx.AsyncClient(trust_env=False, timeout=180) as client:
            # Qwen accepts one leading system message. Retain recent session notes alongside the instructions.
            notes = [message["content"] for message in messages[1:] if message["role"] == "system"]
            history = [message for message in messages if message["role"] != "system"]
            body = {"model": "badshop", "messages": [{"role": "system", "content": "\n\n".join([PROMPT, *notes[-2:]])},
                                                    *history],
                    "temperature": 0, "max_tokens": 320, "chat_template_kwargs": {"enable_thinking": False}}
            if tools:
                definitions = [deepcopy(tool) for tool in tools if tool["function"]["name"] in TOOLS]
                image_ids = []
                if isinstance(user, list):
                    for part, preview in zip(user, user[1:]):
                        match = ARTIFACT.search(part.get("text", ""))
                        if match and preview.get("type") == "image_url":
                            image_ids.append(match[1])
                for tool in definitions:
                    image = tool["function"].get("parameters", {}).get("properties", {}).get("image")
                    if image is not None and image_ids:
                        image["enum"] = image_ids
                body["tools"] = definitions
            message = await self._request(client, body)
        try:
            text = message.get("content") or ""
            calls = [ToolCallRequest(call["id"], call["function"]["name"], call["function"]["arguments"])
                     for call in message.get("tool_calls") or []]
        except (KeyError, TypeError, ValueError):
            raise ProviderError("On-device AI returned an invalid edit. Try again.") from None
        if len(calls) > 1 or any(call.name not in TOOLS for call in calls):
            return Reply("On-device AI can make one basic edit at a time. Try asking for one change.")
        if text:
            on_delta(text)
        return Reply(text, calls)

    async def _request(self, client: httpx.AsyncClient, body: dict) -> dict:
        url, key = await self._endpoint()
        try:
            response = await client.post(url + "/v1/chat/completions", json=body,
                                         headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            return response.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            raise ProviderError("On-device AI could not finish the request. Try again with a shorter request "
                                "or start a new session.") from None

    async def _laser(self, prompt: str, content: list | str, turn: list[dict]) -> Reply:
        # Let the detector supply the geometry. The model only identifies a numbered person.
        images = {}
        if isinstance(content, list):
            for part, preview in zip(content, content[1:]):
                match = ARTIFACT.search(part.get("text", ""))
                if match and preview.get("type") == "image_url":
                    images[match[1]] = preview
        calls = [call for message in turn for call in message.get("tool_calls", ())]
        if not calls:
            attached = [aid for aid in images if f"[image {aid[:8]}:" in prompt]
            choices = attached or list(images)
            if len(choices) != 1:
                return Reply("Attach one photo for the laser eyes.")
            return Reply(tool_calls=[ToolCallRequest("local_" + uuid.uuid4().hex, "find", {"image": choices[0]})])
        call = calls[-1]
        result = next((item["content"] for item in reversed(turn) if item.get("tool_call_id") == call["id"]), "")
        if call["function"]["name"] == "eyes":
            if result.startswith(NOT_APPLIED):
                return Reply("The laser eyes weren’t applied.")
            return Reply("Laser eyes added.")
        try:
            image = json.loads(call["function"]["arguments"])["image"]
            faces = json.loads(result.rsplit("\nstructured_data: ", 1)[1])["faces"]
        except (IndexError, KeyError, TypeError, ValueError):
            image, faces = "", []
        if not faces or image not in images:
            return Reply("I couldn’t locate eyes in that photo. Try a clearer photo with the faces visible.")

        positions = ", ".join(f"{i}: face centered at x={round((face['box'][0] + face['box'][2]) / 2)}"
                              for i, face in enumerate(faces, 1))
        request = (f"Request: {prompt}\nThe faces are numbered from left to right: {positions}. "
                   "Look at the photo and identify the one person requested. Return their face number. "
                   "Return 0 if the description is ambiguous or the person is absent.")
        schema = {"type": "object", "properties": {"face": {"enum": list(range(len(faces) + 1))}},
                  "required": ["face"], "additionalProperties": False}
        async with httpx.AsyncClient(trust_env=False, timeout=180) as client:
            message = await self._request(client, {
                "model": "badshop", "temperature": 0, "max_tokens": 32,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {"name": "face", "schema": schema}},
                "messages": [{"role": "user", "content": [{"type": "text", "text": request}, images[image]]}],
            })
        try:
            face = json.loads(message["content"])["face"]
        except (KeyError, TypeError, ValueError):
            face = 0
        if type(face) is not int or not 1 <= face <= len(faces):
            return Reply("Which person should get laser eyes? Try describing their position or clothing.")
        return Reply(tool_calls=[ToolCallRequest("local_" + uuid.uuid4().hex, "eyes",
                                               {"image": image, "at": faces[face - 1]["eyes"]})])
