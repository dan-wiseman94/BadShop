"""Optional binary artifact replies on the existing authenticated WebSocket.

BSM1, a four-byte big-endian metadata length, a validated JSON-RPC envelope,
then the exact encoded image. JSON clients retain the existing artifact API.
No new listener, path grant or URL token is introduced.
"""

import json
from contextvars import ContextVar
from badshop.engine.errors import EngineError

METHODS = frozenset({'artifacts.get', 'artifacts.frame'})
MAX_BYTES = 64 * 2**20
MAX_HEADER = 2**20
BINARY_ARTIFACTS = ContextVar('binary_artifacts', default=False)


def encode(envelope: dict) -> bytes:
    payload = dict(envelope['result'])
    data = payload.pop('data')
    payload['byte_length'] = len(data)
    header = json.dumps({**envelope, 'result': payload}, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    if not isinstance(data, bytes) or len(data) > MAX_BYTES or len(header) > MAX_HEADER:
        raise EngineError('the requested image exceeds the view transport budget', hint='request a thumbnail or export the original')
    return b'BSM1' + len(header).to_bytes(4, 'big') + header + data
