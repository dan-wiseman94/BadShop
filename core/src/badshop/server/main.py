"""`badshop-core`: the headless core that the desktop shell (and, from Plan 5, MCP proxies) talk to."""

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import signal
import socket
import sys
import threading

from badshop import __version__
from badshop.server.app import CoreApp
from badshop.server.settings import load_settings
from badshop.server.ws import bound_port, serve


def _port(text: str) -> int:
    n = int(text) if text.isdigit() else -1
    if not 0 <= n <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port number (0-65535; 0 picks a free one)")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="badshop-core", description="The badshop core: sessions, tools and the "
                                "agent, served to the app over a local WebSocket.")
    p.add_argument("--version", action="version", version=f"badshop-core {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="serve the local API; the first stdout line is the port and token")
    s.add_argument("--port", type=_port, default=0, help="port on 127.0.0.1 (default: a free one)")
    return p


def _stdout_to_stderr() -> None:
    """After the handshake stdout carries nothing more: point it at stderr (the log), so a stray print from a
    library or the tool worker can neither break the protocol nor block on a pipe nobody reads."""
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())


def _install_stop() -> asyncio.Event:
    """From now on SIGINT (Ctrl-C) and SIGTERM (the shell quitting) set the returned event instead of
    killing the process."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops have no signal handlers
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    return stop


def _stop_at_stdin_eof(stop: asyncio.Event) -> None:
    """When stdin is not a terminal, set `stop` once stdin reaches end of file (spec §5.7). The desktop
    shell spawns the core with a stdin pipe it never writes to: if the shell dies without stopping the core,
    its end of the pipe closes, and the core stops as on SIGTERM instead of running on with nobody to serve.
    Anything written to stdin is read and dropped. A terminal is left alone (Ctrl-C stops the core there)."""
    if sys.stdin is None:  # started without a stdin at all (fd 0 closed): nothing to watch
        return
    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError):
        return
    if os.isatty(fd):
        return
    loop = asyncio.get_running_loop()

    def at_eof() -> None:
        if stop.is_set():  # a signal came first
            return
        stop.set()  # before the message: a dead shell may have taken the stderr pipe with it
        with contextlib.suppress(OSError):
            print("badshop-core: stdin closed (whoever started the core is gone); stopping",
                  file=sys.stderr, flush=True)

    def wait_for_eof() -> None:
        try:
            while os.read(fd, 65536):
                pass
        except OSError:  # an unreadable stdin (GNU nohup gives it /dev/null opened write-only)
            return
        with contextlib.suppress(RuntimeError):  # the loop has closed: the core stopped already
            loop.call_soon_threadsafe(at_eof)

    threading.Thread(target=wait_for_eof, name="badshop-stdin", daemon=True).start()


async def _serve(port: int) -> int:
    # Bind before the app exists: CoreApp sets the last run's autosave aside for its restore offer as soon
    # as it is made (Task 12), and a start that can't listen must leave it for the next one to offer.
    try:
        listener = socket.create_server(("127.0.0.1", port))
    except OSError as e:
        print(f"badshop-core: can't listen on 127.0.0.1:{port} ({e.strerror or e})", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(32)
    try:
        app = CoreApp(load_settings())
        server = await serve(app, token, sock=listener)  # from here on the server owns the socket
    except BaseException:
        listener.close()
        raise
    try:
        stop = _install_stop()  # before the handshake line: the shell may stop the core as soon as it reads it
        _stop_at_stdin_eof(stop)  # ... or die without stopping it
        print(json.dumps({"port": bound_port(server), "token": token}), flush=True)
        _stdout_to_stderr()
        await stop.wait()
    finally:
        server.close()  # every client gets 1001; each connection cancels the requests it still has open
        app.session.executor.cancel()  # a tool one of them is running stops now, not at its time limit
        await server.wait_closed()  # returns once every connection and every request has ended
        await app.close()  # stops the turn (as if the UI had closed), autosaves, closes the tool worker
    return 0


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return asyncio.run(_serve(a.port))  # a.cmd is "serve", the only command until Plan 5 adds "mcp"
