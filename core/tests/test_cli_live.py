"""Explicit opt-in smoke: BADSHOP_LIVE_CLI=claude|codex|gemini pytest tests/test_cli_live.py.

Runs two real CLI turns including a resumed MCP image view and may consume account
usage. Never runs by default. The chosen CLI must already have terminal login or its
supported API-key environment variable. BADSHOP_LIVE_CLI_MODEL optionally selects a model.
BADSHOP_LIVE_CLI_TIMEOUT_S bounds both turns together (default 240 seconds);
BADSHOP_LIVE_CLI_TRACE=1 prints event kinds/timing and redacted failure diagnostics.
"""

import asyncio
import io
import os
import json
import time

import pytest
from PIL import Image

from badshop.providers.cli_provider import CLIProvider
from badshop.providers.profiles import Profile
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.server.ws import bound_port, serve
from badshop.session.execution import InProcessExecutor
from badshop.diagnostics import redact

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
        trace = os.environ.get("BADSHOP_LIVE_CLI_TRACE") == "1"
        started = time.monotonic()

        def event(event):
            if trace:
                raw = event.get("raw")
                print(json.dumps({"elapsed_s": round(time.monotonic() - started, 1), "kind": event.get("kind"),
                                  "type": raw.get("type") if isinstance(raw, dict) else "raw-line"}), flush=True)
        try:
            cli = os.environ["BADSHOP_LIVE_CLI"]
            provider = CLIProvider(Profile(kind="cli", cli=cli, label="smoke",
                                           model=os.environ.get("BADSHOP_LIVE_CLI_MODEL", "")),
                                   f"ws://127.0.0.1:{bound_port(server)}", "live-smoke-private-token")
            with io.BytesIO() as buffer, Image.new("RGB", (32, 32), "red") as image:
                image.save(buffer, "PNG")
                artifact = app.session.import_image(buffer.getvalue(), "live-smoke-color")
            async with asyncio.timeout(float(os.environ.get("BADSHOP_LIVE_CLI_TIMEOUT_S", "240"))):
                answer = await provider.turn(
                    f"Use the badshop view MCP tool to inspect artifact {artifact.id}, then report its main color. "
                    "Do not guess without opening the image and do not use any other tools.",
                    lambda _: None, event)
                if trace:
                    print(json.dumps({"elapsed_s": round(time.monotonic() - started, 1),
                                      "image_reply": redact(answer)}), flush=True)
                assert "red" in answer.lower()
                assert any(s.tool == "view" and s.status == "done" for s in app.session.data.steps)
                session_id = provider.session_id
                assert session_id, "the next turn must resume the existing conversation"
                step_count = len(app.session.data.steps)
                answer = await provider.turn("What main color was the image you just inspected? "
                                             "Reply briefly, using the previous conversation; do not call any tools.",
                                             lambda _: None, event)
                if trace:
                    print(json.dumps({"elapsed_s": round(time.monotonic() - started, 1),
                                      "resume_reply": redact(answer), "same_session": provider.session_id == session_id}),
                          flush=True)
                assert "red" in answer.lower() and provider.session_id == session_id
                assert len(app.session.data.steps) == step_count
        except BaseException:
            if trace and provider:
                print(json.dumps(redact({"elapsed_s": round(time.monotonic() - started, 1),
                                         "stderr": list(provider._stderr),
                                         "steps": [(s.tool, s.status) for s in app.session.data.steps]})), flush=True)
            raise
        finally:
            if provider:
                await provider.close()
            server.close()
            await server.wait_closed()
            await app.close()
    asyncio.run(body())
