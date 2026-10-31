"""MCP SDK v2 stdio server forwarding only the three CLI-authorized RPC methods."""

import asyncio
import json
from urllib.parse import urlsplit

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams, CallToolResult, ImageContent, ListToolsResult,
    PaginatedRequestParams, TextContent, Tool, ToolAnnotations,
)
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from badshop.agent.context import model_result
from badshop.session.models import Step


class CoreError(Exception):
    """A core refusal, returned to the CLI as an MCP tool error."""


class CoreConnection:
    def __init__(self, url: str, token: str, actor: str):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("MCP must connect to the local badshop core")
        if actor not in ("cli:claude", "cli:codex", "cli:gemini"):
            raise ValueError("MCP requires a CLI actor")
        self.url, self.token, self.actor = url, token, actor

    async def call(self, method: str, params: dict | None = None):
        if method not in ("tools.list", "tools.run", "artifacts.get"):
            raise CoreError("method is outside the MCP tool scope")
        # A separate connection per request lets cancellation close precisely that tool call.
        # Closing its socket cancels the server request and rejects a pending approval.
        async with connect(self.url, max_size=64 * 2**20, compression=None) as ws:
            await ws.send(json.dumps({"type": "hello", "token": self.token, "actor": self.actor}))
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if hello.get("type") != "welcome":
                raise CoreError("the badshop core refused the MCP connection")
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                      "params": params or {}}))
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("id") != 1:
                    continue  # session events belong to the UI; no proxy state
                if "error" in msg:
                    err = msg["error"]
                    hint = (err.get("data") or {}).get("hint")
                    raise CoreError(err["message"] + (f"\nhint: {hint}" if hint else ""))
                return msg["result"]
        raise CoreError("the badshop core disconnected")


def build_server(connection: CoreConnection, *, heartbeat_s: float = 60) -> Server:
    if heartbeat_s <= 0:
        raise ValueError("heartbeat must be positive")

    async def listed(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        entries = await connection.call("tools.list")
        return ListToolsResult(tools=[Tool(
            name=t["name"], description=t["description"], input_schema=t["schema"],
            annotations=ToolAnnotations(read_only_hint=t["read_only"],
                                        destructive_hint=t["writes_files"]),
        ) for t in entries])

    async def called(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        async def heartbeat():
            count = 0
            while True:
                await asyncio.sleep(heartbeat_s)
                count += 1
                if ctx.meta and "progress_token" in ctx.meta:
                    await ctx.session.send_progress_notification(
                        ctx.meta["progress_token"], count, message="badshop: running or waiting for approval")
                else:
                    # Progress notifications require a client-supplied token. A protocol logging
                    # notification still keeps stdio active for clients that omit that token.
                    await ctx.session.send_log_message("info", "badshop: running or waiting for approval",
                                                       logger="badshop")

        beat = asyncio.create_task(heartbeat())
        try:
            step = await connection.call("tools.run", {"tool": params.name,
                                                        "params": params.arguments or {}})
            content = [TextContent(type="text", text=model_result(Step.model_validate(step)))]
            for aid in step.get("outputs", [])[:8]:
                image = await connection.call("artifacts.get", {"id": aid, "max_px": 1024})
                content.append(ImageContent(type="image", data=image["data"], mime_type=image["mime"]))
            return CallToolResult(content=content, is_error=step["status"] in ("error", "rejected"))
        except CoreError as e:
            return CallToolResult(content=[TextContent(type="text", text=str(e))], is_error=True)
        except (OSError, ValueError, ConnectionClosed, TimeoutError) as e:
            return CallToolResult(content=[TextContent(type="text", text=f"core connection failed: {e}")],
                                  is_error=True)
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)

    return Server("badshop", on_list_tools=listed, on_call_tool=called)


async def run_stdio(url: str, token: str, actor: str, *, heartbeat_s: float = 60) -> None:
    server = build_server(CoreConnection(url, token, actor), heartbeat_s=heartbeat_s)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
