"""Validate fault injection over real loopback TLS without modifying OS trust."""
import http.client
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'packaging'))
from accept_update_server import UpdateServer


class UpdateServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b'authentic installer bytes' * 100000
        (self.root / 'candidate.exe').write_bytes(self.data)
        (self.root / 'latest.json').write_text('{"version":"1.0.0"}')
        self.environment = patch.dict(os.environ, GITHUB_ACTIONS='true')
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Only certificate-store commands are mocked. The transport is real TLS.
        self.commands = patch('accept_update_server.subprocess.run')
        self.commands.start()
        self.addCleanup(self.commands.stop)
        self.server = UpdateServer(self.root, self.root, self.root).__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def request(self):
        sock = socket.create_connection(self.server.server.server_address, timeout=5)
        sock.sendall(b'CONNECT github.com:443 HTTP/1.1\r\nHost: github.com:443\r\n\r\n')
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            header += sock.recv(1)
        self.assertIn(b'200 Connection established', header)
        context = ssl.create_default_context(cafile=str(self.root / 'acceptance.pem'))
        tls = context.wrap_socket(sock, server_hostname='github.com')
        self.addCleanup(tls.close)
        tls.sendall(b'GET /candidate.exe HTTP/1.1\r\nHost: github.com\r\nConnection: close\r\n\r\n')
        response = http.client.HTTPResponse(tls)
        response.begin()
        self.addCleanup(response.close)
        return response

    def test_interruption_keeps_declared_length_and_closes_early(self):
        with self.assertRaises(http.client.IncompleteRead):
            self.request().read()

    def test_tampering_changes_one_byte_without_changing_length(self):
        self.server.mode = 'tampered'
        actual = self.request().read()
        self.assertEqual(len(actual), len(self.data))
        self.assertNotEqual(actual[0], self.data[0])
        self.assertEqual(actual[1:], self.data[1:])

    def test_authentic_retry_delivers_exact_original_bytes(self):
        self.server.mode = 'authentic'
        self.assertEqual(self.request().read(), self.data)


if __name__ == '__main__':
    unittest.main()
