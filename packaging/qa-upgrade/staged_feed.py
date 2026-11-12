import http.server
import json
import shutil
import socket
import ssl
import threading
from pathlib import Path

FEED = "/dan-wiseman94/BadShop/releases/latest/download/latest.json"
PREFIX = "/dan-wiseman94/BadShop/releases/download/v0.4.2/"


class StagedFeed:
    def __init__(self, root, downloads, asset_name="badshop_0.4.2_amd64.AppImage"):
        self.mode = "interrupt"
        self.requests = []
        self.feed = (downloads / "latest.json").read_bytes()
        self.asset = downloads / asset_name
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root / "chain.pem", root / "server.key")

        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_CONNECT(handler):
                if handler.path != "github.com:443":
                    handler.send_error(403)
                    return
                handler.send_response(200, "Connection Established")
                handler.end_headers()
                with tls.wrap_socket(handler.connection, server_side=True) as client:
                    Origin(client, handler.client_address, handler.server)

            def log_message(handler, *args):
                pass

        class Origin(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                mode = self.mode
                self.requests.append((handler.path, mode))
                print(f"stage: {mode} {handler.path}", flush=True)
                if handler.path == FEED:
                    handler.send_body(self.feed, "application/json")
                elif handler.path == PREFIX + self.asset.name:
                    if mode == "tampered":
                        handler.send_body(b"changed update payload", "application/octet-stream")
                    else:
                        handler.send_response(200)
                        handler.send_header("Content-Length", str(self.asset.stat().st_size))
                        handler.end_headers()
                        with self.asset.open("rb") as stream:
                            if mode == "interrupt":
                                handler.wfile.write(stream.read(4 * 1024 * 1024))
                                handler.connection.shutdown(socket.SHUT_WR)
                            else:
                                shutil.copyfileobj(stream, handler.wfile, length=1024 * 1024)
                else:
                    handler.send_error(404)

            def send_body(handler, data, mime):
                handler.send_response(200)
                handler.send_header("Content-Type", mime)
                handler.send_header("Content-Length", str(len(data)))
                handler.end_headers()
                handler.wfile.write(data)

            def log_message(handler, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"
