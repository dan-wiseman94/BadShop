"""Exercise a frozen core's real OS keychain with a disposable loopback-only credential."""
import asyncio
import contextlib
import json
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import keyring


async def exercise_keychain(rpc) -> None:
    profile_id = 'desktop-smoke-' + uuid.uuid4().hex
    credential = secrets.token_urlsafe(32)
    authenticated = threading.Event()
    reference = None

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never print request headers or the synthetic secret.

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            if self.path != '/v1/chat/completions' or self.headers.get('Authorization') != 'Bearer ' + credential:
                self.send_error(401)
                return
            authenticated.set()
            chunks = [{'id': 'smoke', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'smoke',
                       'choices': [{'index': 0, 'delta': {'content': 'OK'}, 'finish_reason': None}]},
                      {'id': 'smoke', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'smoke',
                       'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
            body = ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body.encode())))
            self.end_headers()
            self.wfile.write(body.encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        profile = await rpc('providers.save', profile={
            'id': profile_id, 'label': 'Disposable native smoke credential',
            'kind': 'openai_compatible', 'model': 'openai/smoke',
            'api_base': f'http://127.0.0.1:{server.server_port}/v1',
            'capability_overrides': {'vision': True, 'tool_calls': True},
        }, api_key=credential)
        reference = profile['api_key_ref']
        result = await rpc('providers.test', profile_id=profile_id, probe=True)
        assert result['status'] == 'ready' and authenticated.is_set(), result
        # Retrieval above happens inside the frozen executable, including macOS's
        # application-specific access control. Read the now-absent slot externally
        # only after deletion, so this check cannot cause a cross-app access prompt.
        await rpc('providers.delete', profile_id=profile_id)
        assert await asyncio.to_thread(keyring.get_password, 'badshop.providers', reference) is None
        print('Frozen keychain smoke passed: stored, retrieved for loopback authentication, deleted', flush=True)
    finally:
        with contextlib.suppress(Exception):
            await rpc('providers.delete', profile_id=profile_id)
        if reference:
            # Also clean up when the core disconnected before its deletion RPC.
            with contextlib.suppress(keyring.errors.PasswordDeleteError):
                await asyncio.to_thread(keyring.delete_password, 'badshop.providers', reference)
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
