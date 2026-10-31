"""Explicit opt-in smoke against a real vision provider; never enabled by ordinary tests.

BADSHOP_LIVE_MODEL=ollama_chat/your-model BADSHOP_LIVE_API_BASE=http://localhost:11434 \\
    uv run pytest -m live tests/test_live_provider.py

Set BADSHOP_LIVE_TOOL_CALLS=false to exercise JSON-mode fallback. Cloud requests additionally
require BADSHOP_LIVE_ALLOW_CLOUD=1; an optional key is read only from BADSHOP_LIVE_API_KEY.
BADSHOP_LIVE_TIMEOUT_S overrides the 90-second limit for slower local/reasoning models.
No profile, keychain, login, or global credential configuration is modified.
"""

import asyncio
import base64
import io
import os
from urllib.parse import urlsplit

import pytest
from PIL import Image

from badshop.providers.litellm_provider import LiteLLMProvider, close_clients


@pytest.mark.live
def test_live_vision_and_tool_request():
    model = os.environ.get("BADSHOP_LIVE_MODEL")
    if not model:
        pytest.skip("set BADSHOP_LIVE_MODEL to opt into real provider requests")
    base = os.environ.get("BADSHOP_LIVE_API_BASE")
    local = base and urlsplit(base).hostname in {"localhost", "127.0.0.1", "::1"}
    # Ollama's default endpoint is loopback. Every other endpoint needs explicit cloud consent.
    local = local or (not base and model.startswith(("ollama/", "ollama_chat/")))
    if not local and os.environ.get("BADSHOP_LIVE_ALLOW_CLOUD") != "1":
        pytest.skip("set BADSHOP_LIVE_ALLOW_CLOUD=1 to permit a possibly paid cloud request")
    buffer = io.BytesIO()
    with Image.new("RGB", (32, 32), "red") as image:
        image.save(buffer, "PNG")
    messages = [{"role": "system", "content": "Inspect the supplied image, then call inspect_color with its main color."},
                {"role": "user", "content": [
                    {"type": "text", "text": "What color is this? Call inspect_color now."},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()}},
                ]}]
    tools = [{"type": "function", "function": {"name": "inspect_color", "description": "Report an image's color",
              "parameters": {"type": "object", "properties": {"color": {"type": "string", "enum": ["red", "blue"]}},
                             "required": ["color"], "additionalProperties": False}}}]
    provider = LiteLLMProvider(model, api_base=base, api_key=os.environ.get("BADSHOP_LIVE_API_KEY"),
                              capability_overrides={"vision": True,
                                                    "tool_calls": os.environ.get("BADSHOP_LIVE_TOOL_CALLS", "true").lower() != "false"},
                              timeout_s=float(os.environ.get("BADSHOP_LIVE_TIMEOUT_S", "90")))
    async def run():
        try:
            return await provider.complete(messages, tools, lambda _: None)
        finally:
            await close_clients()
    reply = asyncio.run(run())
    assert reply.tool_calls and reply.tool_calls[0].name == "inspect_color"
    import json
    arguments = reply.tool_calls[0].arguments
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    assert arguments == {"color": "red"}
