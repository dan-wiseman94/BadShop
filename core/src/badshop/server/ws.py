"""The WebSocket transport (spec §5.6): a token handshake, then JSON-RPC 2.0 in text frames both ways."""

import asyncio
import contextlib
import hmac
import json
import logging
import re
import socket
import sys
from dataclasses import dataclass
from collections.abc import Callable

from websockets.asyncio.server import Server, ServerConnection
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed
from websockets.frames import CloseCode
from pydantic import ValidationError

from badshop import __version__
from badshop.build_identity import build_identity
from badshop.server.protocol import PROTOCOL_VERSION, DocumentContext, Welcome
from badshop.server.app import CoreApp
from badshop.server.auth import actor_token
from badshop.server.queues import MessageQueue
from badshop.server.rpc import INTERNAL_ERROR
from badshop.server import rpc
from badshop.server.grants import AdapterGrant

HELLO_TIMEOUT_S = 10.0
MAX_MESSAGE = 64 * 2**20  # a big photo sent to artifacts.import as base64
MAX_REQUESTS = 64  # never retain an unbounded number of long-running calls per socket
MAX_REQUEST_BYTES = 64 * 2**20
ACTOR = re.compile(r"user|updater|cli:(claude|codex|gemini)")  # agent:* actors live in the core, never on a socket
ORIGINS = [None, "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
           re.compile(r"http://(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]+")]

log = logging.getLogger("badshop.server")


@dataclass
class _Clients:
    users: int = 0  # open connections whose actor is "user"


async def _hello(ws: ServerConnection, token: str, app: CoreApp) -> tuple[str, AdapterGrant | None] | None:
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
    elif not isinstance(actor, str) or not ACTOR.fullmatch(actor):
        reason = "unknown actor"
    elif 'protocol' in msg and (type(msg['protocol']) is not int or msg['protocol'] != PROTOCOL_VERSION):
        reason = "incompatible protocol; update the app and core together"
    elif not isinstance(given, str):
        reason = "bad token"
    elif actor.startswith('cli:') and hasattr(app, 'authenticate_cli'):
        try:
            context = DocumentContext.model_validate(msg['context']) if 'context' in msg else None
        except ValidationError:
            await ws.close(CloseCode.POLICY_VIOLATION, 'invalid document context')
            return None
        grant = app.authenticate_cli(given, actor, token, context)
        if grant is not None:
            return grant.execution_actor, grant
        reason = 'bad token'
    elif not hmac.compare_digest(given.encode("utf-8", "surrogatepass"), actor_token(token, actor).encode("utf-8")):
        reason = 'bad token'
    else:
        return actor, None
    await ws.close(CloseCode.POLICY_VIOLATION, reason)
    return None


async def _write(ws: ServerConnection, outbox: asyncio.Queue) -> None:
    """The connection's only writer: replies and events leave in the order they were queued."""
    with contextlib.suppress(ConnectionClosed):
        while True:
            await ws.send(await outbox.get())


async def _answer(app: CoreApp, raw: str, actor: str, enqueue: Callable[[str], None],
                  grant: AdapterGrant | None = None, connection_run_id: str | None = None) -> None:
    request_id = None
    try:
        if grant is not None:
            try:
                request = json.loads(raw)
            except (ValueError, RecursionError):
                request = None  # The dispatcher reports malformed JSON normally.
            if isinstance(request, dict) and isinstance(request.get('method'), str):
                candidate = request.get('id')
                request_id = candidate if isinstance(candidate, (str, int)) and not isinstance(candidate, bool) else None
                if not grant.standalone and request['method'] != 'tools.list' and grant.run_id != connection_run_id:
                    raise rpc.RpcError(rpc.FORBIDDEN, 'This CLI connection belongs to another run.')
                context, run_id = app.authorize_cli(grant, request['method'])
                request.pop('context', None)
                request.pop('run_id', None)
                if context is not None:
                    request['context'] = context
                if run_id is not None:
                    request['run_id'] = run_id
                raw = json.dumps(request)
        reply = await app.dispatcher.handle(raw, actor)
    except rpc.RpcError as error:
        reply = rpc.error_response(request_id, error)
    except Exception:  # the dispatcher answers every frame itself, so this is a bug; still answer
        log.exception("a request crashed the dispatcher")
        reply = json.dumps({"jsonrpc": "2.0", "id": None, "error": {
            "code": INTERNAL_ERROR, "message": "internal error",
            "data": {"hint": "Check the current session before repeating this action.", "outcome": "unknown"}}})
    if reply is not None:
        enqueue(reply)


async def _connection(app: CoreApp, token: str, clients: _Clients, ws: ServerConnection) -> None:
    grant = None
    try:
        identity = await _hello(ws, token, app)
        if identity is None:
            return
        actor, grant = identity
        await ws.send(Welcome(actor=grant.actor if grant else actor, version=__version__, build_id=build_identity(),
                              core_instance_id=app.core_instance_id, event_seq=app._event_seq,
                              capabilities=['document-context', 'ordered-events'] +
                                           (['cli-session-grant'] if grant and not grant.standalone else []),
                              context=app._document_context() if grant else None).model_dump_json())
    except ConnectionClosed:  # gone before the handshake finished
        if grant is not None and grant.standalone:
            app._grants.revoke(grant)
        return
    outbox = MessageQueue()
    connection_run_id = grant.run_id if grant else None
    closing: asyncio.Task | None = None

    def overload() -> None:
        nonlocal closing
        if closing is None:
            closing = asyncio.create_task(ws.close(CloseCode.TRY_AGAIN_LATER, "client is too far behind"))

    def enqueue(message: str) -> None:
        if closing is not None:
            return
        try:
            outbox.put_nowait(message)
        except asyncio.QueueFull:
            overload()

    async def send(message: str) -> None:
        if grant is not None:
            if grant.revoked or grant.document_incarnation != app.session.incarnation:
                return
            if not grant.standalone and (grant.run_id is None or grant.run_id != connection_run_id):
                return
        enqueue(message)

    writer = asyncio.create_task(_write(ws, outbox))
    requests: set[asyncio.Task] = set()  # in flight; the strong refs keep them alive
    request_bytes = 0
    unsubscribe = app.subscribe(send, on_overflow=overload)
    if actor == "user":
        clients.users += 1
    try:
        async for raw in ws:
            if not isinstance(raw, str):
                await ws.close(CloseCode.UNSUPPORTED_DATA, "JSON-RPC goes in text frames")
                break
            # Each request runs as its own task, so a long tools.run never holds up an approval.respond.
            size = sys.getsizeof(raw)
            if len(requests) >= MAX_REQUESTS or request_bytes + size > MAX_REQUEST_BYTES:
                overload()
                break
            request_bytes += size
            task = asyncio.create_task(_answer(app, raw, actor, enqueue, grant, connection_run_id))
            requests.add(task)
            def finished(task, size=size):
                nonlocal request_bytes
                requests.discard(task)
                request_bytes -= size
            task.add_done_callback(finished)
    except ConnectionClosed:  # an error code, or no close frame at all: the UI process died
        pass
    finally:
        if grant is not None and grant.standalone:
            app._grants.revoke(grant)
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
        await asyncio.gather(writer, *pending, *([closing] if closing else []), return_exceptions=True)


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
    return await ws_serve(handler, max_size=MAX_MESSAGE, compression=None, origins=ORIGINS, **where)


def bound_port(server: Server) -> int:
    return server.sockets[0].getsockname()[1]
