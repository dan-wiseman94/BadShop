"""Bounded, repeatable fuzzing of the JSON-RPC dispatcher."""

import asyncio
import json

from hypothesis import given, settings, strategies as st
from pydantic import StrictInt

from badshop.server import rpc

TEXT = st.text(max_size=40)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | TEXT,
    lambda value: st.lists(value, max_size=4) | st.dictionaries(TEXT, value, max_size=4),
    max_leaves=12,
)
ALLOWED_ACTORS = {
    "user": ("user",),
    "any": ("user", "cli:codex"),
    "updater": ("user", "updater"),
}
RPC_IDS = st.none() | st.integers() | TEXT
INVALID_IDS = st.one_of(
    st.booleans(), st.floats(allow_nan=False, allow_infinity=False),
    st.lists(JSON, max_size=2), st.dictionaries(TEXT, JSON, max_size=2),
)


@settings(max_examples=80, derandomize=True)
@given(raw=st.one_of(
    JSON.map(lambda value: json.dumps({"payload": value})),
    st.lists(JSON, max_size=4).map(json.dumps),
    TEXT.map(lambda value: "!" + value),
))
def test_non_request_frames_return_protocol_errors(raw):
    dispatcher = rpc.Dispatcher()
    reply = json.loads(asyncio.run(dispatcher.handle(raw, "user")))
    code = rpc.PARSE_ERROR if raw.startswith("!") else rpc.INVALID_REQUEST
    assert (reply["jsonrpc"], reply["id"], reply["error"]["code"]) == ("2.0", None, code)
    assert "result" not in reply


@settings(max_examples=100, derandomize=True)
@given(
    request_id=RPC_IDS,
    invalid_id=INVALID_IDS,
    value=st.integers(min_value=-(2**63), max_value=2**63 - 1),
    invalid_params=st.one_of(
        st.none(), st.lists(JSON, max_size=2), TEXT, st.booleans(),
        st.builds(lambda value: {"value": value}, TEXT | st.booleans()),
        st.builds(lambda extra: {"value": 0, "extra": extra}, JSON),
    ),
    actor=st.sampled_from(["user", "cli:codex", "updater"]),
    access=st.sampled_from(tuple(ALLOWED_ACTORS)),
    notification=st.booleans(),
)
def test_rpc_rejects_bad_envelopes_and_params_before_dispatch(
    request_id, invalid_id, value, invalid_params, actor, access, notification,
):
    dispatcher = rpc.Dispatcher()
    calls = []
    allowed = actor in ALLOWED_ACTORS[access]

    @dispatcher.method("set", actors=access)
    async def set_value(actor: str, value: StrictInt):
        calls.append((actor, value))
        return value

    async def send(request):
        raw = await dispatcher.handle(json.dumps(request), actor)
        return None if raw is None else json.loads(raw)

    async def exercise():
        request = {"jsonrpc": "2.0", "method": "set", "params": {"value": value}}
        invalid = await send(dict(request, id=invalid_id))
        assert invalid["id"] is None
        assert invalid["error"]["code"] == rpc.INVALID_REQUEST

        bad_params = await send(dict(request, id=request_id, params=invalid_params))
        assert bad_params["id"] == request_id
        assert bad_params["error"]["code"] == (rpc.INVALID_PARAMS if allowed else rpc.FORBIDDEN)
        message = bad_params["error"]["message"]
        assert isinstance(message, str) and message.strip()
        assert calls == []

        if not notification:
            request["id"] = request_id
        reply = await send(request)
        if notification:
            assert reply is None
        elif allowed:
            assert reply == {"jsonrpc": "2.0", "id": request_id, "result": value}
        else:
            assert reply["id"] == request_id
            assert reply["error"]["code"] == rpc.FORBIDDEN
        assert calls == ([(actor, value)] if allowed else [])

    asyncio.run(exercise())
