"""Loopback-only fault injection for an unmodified installed updater on CI.

Only the disposable runner trusts the temporary certificate. The app keeps its
production endpoint, signing key, signature verification and install implementation.
No credentials are forwarded, and no request reaches an external server.
"""
import contextlib
import datetime
import json
import os
import socketserver
import ssl
import subprocess
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class UpdateServer:
    def __init__(self, candidate, root, output):
        self.candidate, self.root, self.output = candidate, root, output
        self.mode = 'interrupted'
        self.events = []
        self.feed = (candidate / 'latest.json').read_bytes()

    def __enter__(self):
        assert os.environ.get('GITHUB_ACTIONS') == 'true'
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'BadShop isolated acceptance')])
        now = datetime.datetime.now(datetime.UTC)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - datetime.timedelta(minutes=5))
                       .not_valid_after(now + datetime.timedelta(days=1))
                       .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                       .sign(key, hashes.SHA256()))
        self.thumbprint = certificate.fingerprint(hashes.SHA1()).hex()
        cert_path, key_path = self.root / 'acceptance.pem', self.root / 'acceptance.key'
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'github.com')]))
                .issuer_name(name).public_key(leaf_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('github.com')]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        server_cert = self.root / 'acceptance-server.pem'
        server_cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM)
                                + certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.cert_path = cert_path
        import sys
        self.platform = sys.platform
        if sys.platform == 'win32':
            subprocess.run(['certutil', '-user', '-addstore', 'Root', str(cert_path)], check=True)
        elif sys.platform == 'darwin':
            subprocess.run(['sudo', 'security', 'add-trusted-cert', '-d', '-r', 'trustRoot',
                            '-k', '/Library/Keychains/System.keychain', str(cert_path)], check=True)
        else:
            self.linux_cert = Path('/usr/local/share/ca-certificates/badshop-acceptance.crt')
            subprocess.run(['sudo', 'cp', str(cert_path), str(self.linux_cert)], check=True)
            subprocess.run(['sudo', 'update-ca-certificates'], check=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(server_cert, key_path)
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    line = self.rfile.readline().decode('ascii').strip()
                    if line != 'CONNECT github.com:443 HTTP/1.1':
                        owner.events.append({'rejected': line})
                        return
                    while self.rfile.readline().strip():
                        pass
                    self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    self.wfile.flush()
                    with context.wrap_socket(self.connection, server_side=True) as tls:
                        with tls.makefile('rb') as request:
                            method, path, _ = request.readline().decode('ascii').strip().split(' ', 2)
                            while request.readline().strip():
                                pass
                            if method != 'GET':
                                raise ValueError('Only updater GET requests are allowed')
                            event = {'path': path, 'mode': owner.mode}
                            owner.events.append(event)
                            if path.endswith('/latest.json'):
                                payload = owner.feed
                                tls.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                                            + f'Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode()
                                            + payload)
                            else:
                                filename = unquote(urlsplit(path).path.rsplit('/', 1)[-1])
                                file = owner.candidate / filename
                                assert file.parent == owner.candidate and file.is_file(), filename
                                size = file.stat().st_size
                                tls.sendall(f'HTTP/1.1 200 OK\r\nContent-Length: {size}\r\nConnection: close\r\n\r\n'.encode())
                                sent = 0
                                with file.open('rb') as stream:
                                    while chunk := stream.read(1024 * 1024):
                                        if sent == 0 and owner.mode == 'tampered':
                                            chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
                                        tls.sendall(chunk)
                                        sent += len(chunk)
                                        if owner.mode == 'interrupted':
                                            break
                                event['bytes_sent'] = sent
                                event['expected_bytes'] = size
                except (OSError, ValueError) as error:
                    owner.events.append({'error': str(error)})

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True

        self.server = Server(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.proxy = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.old_environment = {key: os.environ.get(key) for key in ('HTTPS_PROXY', 'https_proxy', 'NO_PROXY', 'no_proxy')}
        os.environ.update(HTTPS_PROXY=self.proxy, https_proxy=self.proxy,
                          NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        for key, value in self.old_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        (self.output / 'updater-network.json').write_text(json.dumps(self.events, indent=2))
        if self.platform == 'win32':
            subprocess.run(['certutil', '-user', '-delstore', 'Root', self.thumbprint], check=True)
        elif self.platform == 'darwin':
            subprocess.run(['sudo', 'security', 'delete-certificate', '-Z', self.thumbprint,
                            '/Library/Keychains/System.keychain'], check=True)
        else:
            subprocess.run(['sudo', 'rm', '--', str(self.linux_cert)], check=True)
            subprocess.run(['sudo', 'update-ca-certificates'], check=True)
        with contextlib.suppress(FileNotFoundError):
            (self.root / 'acceptance.key').unlink()
