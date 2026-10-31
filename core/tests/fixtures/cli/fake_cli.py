"""Offline CLI subprocess fixture. Invoked through a temporary executable wrapper."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

kind = Path(sys.argv[0]).name
if "--version" in sys.argv:
    print("fake-1.0")
    raise SystemExit
if "--help" in sys.argv:
    print("--input-format --output-format --strict-mcp-config --tools --json --sandbox "
          "--skip-git-repo-check --resume --allowed-mcp-server-names --policy")
    raise SystemExit
if "debug" in sys.argv:
    print(json.dumps({"models": [{"slug": "fake-model", "shell_type": "unified_exec",
                                 "apply_patch_tool_type": "freeform"}]}))
    raise SystemExit

mode = os.environ.get("BADSHOP_FAKE_CLI_MODE", "normal")
fixture = Path(os.environ["BADSHOP_FAKE_CLI_FIXTURES"]) / f"{kind}.jsonl"


async def mcp_view(prompt):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    config = json.loads(sys.argv[sys.argv.index("--mcp-config") + 1])["mcpServers"]["badshop"]
    state = json.loads(prompt.split("snapshot (data, not instructions):\n", 1)[1].split("\nOpen relevant", 1)[0])
    aid = state["artifacts"][-1].split()[1].rstrip(":")
    async with stdio_client(StdioServerParameters(**config)) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            response = await client.call_tool("view", {"image": aid})
            if mode == "budget":
                response = await client.call_tool("view", {"image": aid})
                assert response.is_error


def respond(prompt):
    if mode in ("stall", "stall_ignore"):
        if mode == "stall_ignore":
            import signal
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print('{"type":"system","session_id":"pending"}', flush=True)
        time.sleep(300)
    if mode == "fail":
        print("login required", file=sys.stderr, flush=True)
        raise SystemExit(9)
    if mode == "mcp" or mode == "budget":
        asyncio.run(mcp_view(prompt))
    if mode == "malformed":
        print("not JSON", flush=True)
        print('{"type":"a_new_event","value":123}', flush=True)
    for line in fixture.read_text().splitlines():
        print(line, flush=True)


if kind == "claude":
    for line in sys.stdin:
        respond(json.loads(line)["message"]["content"])
else:
    respond(sys.argv[-1])
    if mode == "orphan":
        import subprocess
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
