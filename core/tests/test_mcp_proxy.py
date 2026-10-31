"""Real SDK client -> stdio subprocess -> authenticated WS -> session contracts."""

import asyncio
import base64
import os
import sys
from contextlib import asynccontextmanager

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import ImageContent, TextContent

from badshop.mcp.proxy import CoreConnection, CoreError
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.server.ws import bound_port, serve
from badshop.session.execution import InProcessExecutor
from conftest import FIXTURES


@pytest.fixture
def private(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BADSHOP_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


@asynccontextmanager
async def connected(*, heartbeat=.03, timeout=5, mode="auto", logging_callback=None):
    app = CoreApp(Settings(approval_mode=mode), executor_factory=lambda **_: InProcessExecutor())
    token = "test-mcp-private-token"
    server = await serve(app, token)
    url = f"ws://127.0.0.1:{bound_port(server)}"
    app.set_connection(url, token)
    frozen = os.environ.get("BADSHOP_MCP_EXECUTABLE")
    params = StdioServerParameters(command=frozen or sys.executable, args=[
        *([] if frozen else ["-m", "badshop.server"]), "mcp", "--connect", url, "--token", token, "--actor", "cli:claude",
        "--heartbeat-seconds", str(heartbeat)], env=dict(os.environ))
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timeout,
                                     logging_callback=logging_callback) as client:
                await client.initialize()
                yield app, client, CoreConnection(url, token, "cli:claude")
    finally:
        server.close()
        await server.wait_closed()
        await app.close()


def test_sdk_list_call_view_image_errors_and_scope(private):
    async def body():
        async with connected() as (app, client, connection):
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            listed = await client.list_tools()
            tools = {t.name: t for t in listed.tools}
            assert "view" in tools and "paste" in tools
            assert tools["view"].annotations.read_only_hint
            assert "path" not in str(tools["view"].input_schema)
            result = await client.call_tool("view", {"image": imported.id, "grid": True})
            assert not result.is_error
            assert isinstance(result.content[0], TextContent)
            images = [c for c in result.content if isinstance(c, ImageContent)]
            assert images and base64.b64decode(images[0].data).startswith(b"\x89PNG")
            assert app.session.data.steps[-1].actor == "cli:claude"
            result = await client.call_tool("info", {"image": "/etc/passwd"})
            assert result.is_error and result.content[0].text
            result = await client.call_tool("does_not_exist", {})
            assert result.is_error
            with pytest.raises(CoreError, match="outside the MCP tool scope"):
                await connection.call("session.new")
            assert app.session.data.name == "Untitled"
    asyncio.run(body())


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_sdk_progress_during_gated_tool(private, decision):
    async def body():
        async with connected(mode="ask_all") as (app, client, _):
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            reports = []

            async def progress(value, total, message):
                reports.append((value, message))

            task = asyncio.create_task(client.call_tool("view", {"image": imported.id},
                                                         progress_callback=progress))
            while not app._cli_gate.pending():
                await asyncio.sleep(.01)
            await asyncio.sleep(.16)
            assert len(reports) >= 3 and not task.done()
            assert all(a[0] < b[0] for a, b in zip(reports, reports[1:]))
            step_id = app._cli_gate.pending()[0]
            app._cli_gate.respond(step_id, decision, note="contract test")
            result = await task
            assert result.is_error == (decision == "reject")
            assert app.session.step(step_id).status == ("done" if decision == "approve" else "rejected")
    asyncio.run(body())


def test_sdk_cancel_closes_ws_and_rejects_pending_step(private):
    async def body():
        async with connected(mode="ask_all") as (app, client, _):
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            task = asyncio.create_task(client.call_tool("view", {"image": imported.id}))
            while not app._cli_gate.pending():
                await asyncio.sleep(.01)
            step_id = app._cli_gate.pending()[0]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with asyncio.timeout(5):
                while app.session.step(step_id).status == "proposed":
                    await asyncio.sleep(.01)
            assert app.session.step(step_id).status == "rejected"
    asyncio.run(body())


def test_sdk_heartbeat_without_progress_token(private):
    async def body():
        reports = []

        async def logging_callback(params):
            reports.append(params.data)

        async with connected(mode="ask_all", logging_callback=logging_callback) as (app, client, _):
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            task = asyncio.create_task(client.call_tool("view", {"image": imported.id}))
            while not app._cli_gate.pending():
                await asyncio.sleep(.01)
            await asyncio.sleep(.12)
            assert reports and not task.done()
            app._cli_gate.respond(app._cli_gate.pending()[0], "approve")
            assert not (await task).is_error
    asyncio.run(body())


@pytest.mark.skipif(os.environ.get("BADSHOP_LONG_MCP_TEST") != "1", reason="opt-in 61s approval contract")
def test_sdk_real_sixty_second_approval_heartbeat(private):
    async def body():
        async with connected(heartbeat=1, timeout=90, mode="ask_all") as (app, client, _):
            imported = app.session.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln")
            reports = []

            async def progress(value, total, message):
                reports.append(value)

            task = asyncio.create_task(client.call_tool("view", {"image": imported.id},
                                                         progress_callback=progress))
            while not app._cli_gate.pending():
                await asyncio.sleep(.01)
            await asyncio.sleep(61)
            assert len(reports) >= 60 and not task.done()
            app._cli_gate.respond(app._cli_gate.pending()[0], "approve")
            assert not (await task).is_error
    asyncio.run(body())
