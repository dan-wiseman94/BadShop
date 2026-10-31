"""Explicit opt-in smoke: BADSHOP_LIVE_CLI=claude|codex|gemini pytest tests/test_cli_live.py.

Runs two real CLI turns including a resumed MCP image view and may consume account
usage. Never runs by default. The chosen CLI must already have terminal login or its
supported API-key environment variable. BADSHOP_LIVE_CLI_MODEL optionally selects a model.
"""

import asyncio
import io
import os

import pytest
from PIL import Image

from badshop.providers.cli_provider import CLIProvider
from badshop.providers.profiles import Profile
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.server.ws import bound_port, serve
from badshop.session.execution import InProcessExecutor

pytestmark = pytest.mark.live


@pytest.mark.skipif(os.environ.get("BADSHOP_LIVE_CLI") not in ("claude", "codex", "gemini"),
                    reason="explicit real subscription smoke opt-in required")
def test_subscription_cli_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))

    async def body():
        app = CoreApp(Settings(approval_mode="auto"), executor_factory=lambda **_: InProcessExecutor())
        server = await serve(app, "live-smoke-private-token")
        provider = None
        try:
            cli = os.environ["BADSHOP_LIVE_CLI"]
            provider = CLIProvider(Profile(kind="cli", cli=cli, label="smoke",
                                           model=os.environ.get("BADSHOP_LIVE_CLI_MODEL", "")),
                                   f"ws://127.0.0.1:{bound_port(server)}", "live-smoke-private-token")
            async with asyncio.timeout(120):
                answer = await provider.turn("Reply with OK; do not call tools.", lambda _: None, lambda _: None)
            assert answer.strip()
            assert provider.session_id, "the next turn must resume the existing conversation"
            with io.BytesIO() as buffer, Image.new("RGB", (32, 32), "red") as image:
                image.save(buffer, "PNG")
                artifact = app.session.import_image(buffer.getvalue(), "live-smoke-color")
            async with asyncio.timeout(120):
                answer = await provider.turn(
                    f"Use the badshop view MCP tool to inspect artifact {artifact.id}, then report its main color. "
                    "Do not guess without opening the image and do not use any other tools.",
                    lambda _: None, lambda _: None)
            assert "red" in answer.lower()
            assert any(s.tool == "view" and s.status == "done" for s in app.session.data.steps)
        finally:
            if provider:
                await provider.close()
            server.close()
            await server.wait_closed()
            await app.close()
    asyncio.run(body())
