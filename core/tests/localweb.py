"""A tiny raw-socket web server on 127.0.0.1 for network tests.

Each connection gets whatever `reply(conn, path)` writes, byte for byte, so tests can send a
garbage Content-Length, hang up early, trickle a body or redirect anywhere."""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


def response(body: bytes = b"", status: str = "200 OK", headers: dict[str, str | None] | None = None) -> bytes:
    """A raw HTTP/1.1 response; Content-Length is the body's unless `headers` gives one (None drops it)."""
    head = {"Content-Length": str(len(body)), "Connection": "close", **(headers or {})}
    lines = [f"HTTP/1.1 {status}", *(f"{k}: {v}" for k, v in head.items() if v is not None), "", ""]
    return "\r\n".join(lines).encode("latin-1") + body


def canned(raw: bytes) -> Callable[[socket.socket, str], None]:
    """A reply that sends `raw` and hangs up."""
    return lambda conn, path: conn.sendall(raw)


def trickle(every: float = 0.2, length: int = 100_000) -> Callable[[socket.socket, str], None]:
    """A reply that promises `length` bytes and then sends one every `every` seconds (for at most 10 s)."""
    def reply(conn: socket.socket, path: str) -> None:
        conn.sendall(response(headers={"Content-Length": str(length)}))
        for _ in range(int(10 / every)):
            conn.sendall(b"x")
            time.sleep(every)
    return reply


@contextmanager
def serve(reply: Callable[[socket.socket, str], None]) -> Iterator[str]:
    """Serve on a free port until the block ends; yields the base URL (no trailing slash)."""
    srv = socket.create_server(("127.0.0.1", 0))
    srv.settimeout(0.1)
    stop = threading.Event()

    def handle(conn: socket.socket) -> None:
        with conn:
            try:
                request = b""
                while b"\r\n\r\n" not in request:
                    got = conn.recv(4096)
                    if not got:
                        return
                    request += got
                reply(conn, request.split(b" ", 2)[1].decode("latin-1"))
            except OSError:  # the client hung up, as the tests intend
                pass

    def accept() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(None)
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}"
    finally:
        stop.set()
        thread.join(5)
        srv.close()
