"""The WebSocket transport (spec §5.6): a token handshake, then JSON-RPC 2.0 in text frames both ways."""

import asyncio
import contextlib
import hmac
import json
import logging
import re
import socket
from dataclasses import dataclass

from websockets.asyncio.server import Server, ServerConnection
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed
from websockets.frames import CloseCode

from badshop import __version__
from badshop.server.app import CoreApp
from badshop.server.rpc import INTERNAL_ERROR

HELLO_TIMEOUT_S = 10.0
MAX_MESSAGE = 64 * 2**20  # a big photo sent to artifacts.import as base64
ACTOR = re.compile(r"user|cli:(claude|codex|gemini)")  # agent:* actors live in the core, never on a socket

log = logging.getLogger("badshop.server")


@dataclass
class _Clients:
    users: int = 0  # open connections whose actor is "user"


async def _hello(ws: ServerConnection, token: str) -> str | None:
    """The actor the first message names, or None once the connection is closed with 1008."""
    try:
        raw = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S)
    except TimeoutError:
        await ws.close(CloseCode.POLICY_VIOLATION, "no hello")
        return None
    try:
        msg = json.loads(raw) if isinstance(raw, str) else None
    except (ValueError, RecursionError):  # not JSON, or nested too deep for the parser
        msg = None
    given = msg.get("token") if isinstance(msg, dict) else None
    actor = msg.get("actor") if isinstance(msg, dict) else None
    if not isinstance(msg, dict) or msg.get("type") != "hello":
        reason = "the first message must be a hello"
    elif not isinstance(given, str) or not hmac.compare_digest(
            given.encode("utf-8", "surrogatepass"), token.encode("utf-8")):
        reason = "bad token"
    elif not isinstance(actor, str) or not ACTOR.fullmatch(actor):
        reason = "unknown actor"
    else:
        return actor
    await ws.close(CloseCode.POLICY_VIOLATION, reason)
    return None


async def _write(ws: ServerConnection, outbox: asyncio.Queue) -> None:
    """The connection's only writer: replies and events leave in the order they were queued."""
    with contextlib.suppress(ConnectionClosed):
        while True:
            await ws.send(await outbox.get())


async def _answer(app: CoreApp, raw: str, actor: str, outbox: asyncio.Queue) -> None:
    try:
        reply = await app.dispatcher.handle(raw, actor)
    except Exception:  # the dispatcher answers every frame itself, so this is a bug; still answer
        log.exception("a request crashed the dispatcher")
        reply = json.dumps({"jsonrpc": "2.0", "id": None, "error": {
            "code": INTERNAL_ERROR, "message": "internal error",
            "data": {"hint": "this is a bug in badshop; the session is unaffected"}}})
    if reply is not None:
        outbox.put_nowait(reply)


async def _connection(app: CoreApp, token: str, clients: _Clients, ws: ServerConnection) -> None:
    try:
        actor = await _hello(ws, token)
        if actor is None:
            return
        await ws.send(json.dumps({"type": "welcome", "actor": actor, "version": __version__}))
    except ConnectionClosed:  # gone before the handshake finished
        return
    outbox: asyncio.Queue[str] = asyncio.Queue()

    async def send(message: str) -> None:
        outbox.put_nowait(message)

    writer = asyncio.create_task(_write(ws, outbox))
    requests: set[asyncio.Task] = set()  # in flight; the strong refs keep them alive
    unsubscribe = app.subscribe(send)
    if actor == "user":
        clients.users += 1
    try:
        async for raw in ws:
            if not isinstance(raw, str):
                await ws.close(CloseCode.UNSUPPORTED_DATA, "JSON-RPC goes in text frames")
                break
            # Each request runs as its own task, so a long tools.run never holds up an approval.respond.
            task = asyncio.create_task(_answer(app, raw, actor, outbox))
            requests.add(task)
            task.add_done_callback(requests.discard)
    except ConnectionClosed:  # an error code, or no close frame at all: the UI process died
        pass
    finally:
        unsubscribe()
        writer.cancel()
        pending = list(requests)
        for task in pending:  # nobody is left to read the answers
            task.cancel()
        if actor == "user":
            clients.users -= 1
            if clients.users == 0:
                app.on_client_gone()  # the UI is gone: stop the turn, reject what waits for approval
        # Wait for them: a call already in a session thread finishes first, and the server's
        # wait_closed() (so main's app.close()) only returns once every request has ended.
        await asyncio.gather(writer, *pending, return_exceptions=True)


async def serve(app: CoreApp, token: str, host: str = "127.0.0.1", port: int = 0, *,
                sock: socket.socket | None = None) -> Server:
    """Listen for clients of `app` on host:port (port 0: a free one), or on `sock`, a socket that is
    already listening (main binds it before it makes the app). `close()` the returned server (it closes
    `sock` too), then `await wait_closed()`: every connection gets 1001, and it returns once every
    request has ended."""
    clients = _Clients()

    async def handler(ws: ServerConnection) -> None:
        await _connection(app, token, clients, ws)

    where = {"sock": sock} if sock is not None else {"host": host, "port": port}
    # compression=None: on loopback deflate only costs CPU, and most payloads are base64 images anyway
    return await ws_serve(handler, max_size=MAX_MESSAGE, compression=None, **where)


def bound_port(server: Server) -> int:
    return server.sockets[0].getsockname()[1]
