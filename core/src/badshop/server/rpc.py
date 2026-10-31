"""JSON-RPC 2.0 (one request object per text frame; batches are refused) routed to async handlers.

A handler is `async def handler(actor: str, **params) -> result`. Its keyword parameters, with their
annotations and defaults, are the method's parameter schema: the dispatcher validates `params` against
them first, so a missing, unknown or mistyped parameter is a clean INVALID_PARAMS error and the
handler never runs."""

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from badshop.engine.errors import EngineError
from badshop.tools.runner import explain, is_trusted

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
ENGINE_ERROR = -32000  # an EngineError; data {"hint": ...}
FORBIDDEN = -32001  # this actor may not call this method

ACTORS = ("user", "any")

log = logging.getLogger("badshop.server")

Handler = Callable[..., Awaitable[Any]]


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def notification(method: str, params: dict) -> str:
    """A server event: a JSON-RPC notification (no id)."""
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": params})


def _error(id_: Any, e: RpcError) -> str:
    err: dict[str, Any] = {"code": e.code, "message": e.message}
    if e.data is not None:
        err["data"] = e.data
    return json.dumps({"jsonrpc": "2.0", "id": id_, "error": err})


def _valid_id(id_: Any) -> bool:
    return id_ is None or isinstance(id_, str) or (isinstance(id_, int) and not isinstance(id_, bool))


def params_model(name: str, fn: Handler) -> type[BaseModel]:
    """The handler's parameters after `actor`, as a pydantic model that refuses unknown keys."""
    fields: dict[str, Any] = {}
    for p in list(inspect.signature(fn, eval_str=True).parameters.values())[1:]:
        annotation = Any if p.annotation is inspect.Parameter.empty else p.annotation
        fields[p.name] = (annotation, ... if p.default is inspect.Parameter.empty else p.default)
    return create_model(f"Params_{name.replace('.', '_')}",
                        __config__=ConfigDict(extra="forbid", allow_inf_nan=False), **fields)


class Dispatcher:
    def __init__(self) -> None:
        self._methods: dict[str, tuple[Handler, type[BaseModel], str]] = {}

    def method(self, name: str, *, actors: str = "user") -> Callable[[Handler], Handler]:
        """Register an async handler. actors="user": only the trusted user may call it; "any": every
        connected actor may (the handler gets the actor and applies its own rules)."""
        if actors not in ACTORS:
            raise ValueError(f"actors must be one of {ACTORS}, not {actors!r}")
        if name in self._methods:
            raise ValueError(f"method {name!r} is already registered")

        def register(fn: Handler) -> Handler:
            self._methods[name] = (fn, params_model(name, fn), actors)
            return fn

        return register

    def names(self) -> list[str]:
        return sorted(self._methods)

    async def handle(self, raw: str, actor: str) -> str | None:
        """One incoming frame -> the reply frame, or None for a notification (a request without an id).
        Calls are independent, so a transport may await several at once."""
        try:
            msg = json.loads(raw)
        except ValueError:
            return _error(None, RpcError(PARSE_ERROR, "parse error: that is not JSON"))
        except RecursionError:  # e.g. "[" * 100_000: json refuses nesting deeper than the recursion limit
            return _error(None, RpcError(PARSE_ERROR, "parse error: the JSON is nested too deeply"))
        if not isinstance(msg, dict) or not _valid_id(msg.get("id")):
            return _error(None, RpcError(INVALID_REQUEST, "invalid request",
                                         {"hint": "send one JSON-RPC 2.0 request object per message"}))
        id_, is_request = msg.get("id"), "id" in msg
        if msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(id_, RpcError(INVALID_REQUEST, "invalid request",
                                        {"hint": 'a request needs "jsonrpc": "2.0" and a "method" string'}))
        try:
            result = await self._call(msg["method"], msg.get("params", {}), actor)
            return json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}) if is_request else None
        except RpcError as e:
            if not is_request:
                log.warning("notification %s failed: %s", msg["method"], e.message)
            return _error(id_, e) if is_request else None
        except (TypeError, ValueError) as e:  # json can't encode the result: a bug in the handler
            log.exception("%s returned a result that isn't JSON", msg["method"])
            return _error(id_, RpcError(INTERNAL_ERROR, f"internal error ({e})")) if is_request else None

    async def _call(self, method: str, params: Any, actor: str) -> Any:
        entry = self._methods.get(method)
        if entry is None:
            raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")
        fn, model, actors = entry
        if actors == "user" and not is_trusted(actor):
            raise RpcError(FORBIDDEN, f"{actor} may not call {method}",
                           {"hint": "only the user can manage sessions, files and settings"})
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, f"params for {method} must be an object")
        try:
            checked = model.model_validate(params)
        except ValidationError as e:
            raise RpcError(INVALID_PARAMS, f"invalid params for {method}", {"hint": explain(e)}) from None
        try:
            return await fn(actor, **{name: getattr(checked, name) for name in type(checked).model_fields})
        except RpcError:
            raise
        except EngineError as e:
            raise RpcError(ENGINE_ERROR, e.message, {"hint": e.hint}) from None
        except Exception as e:
            log.exception("%s failed", method)
            raise RpcError(INTERNAL_ERROR, f"internal error in {method} ({type(e).__name__}: {e})",
                           {"hint": "this is a bug in badshop; the session is unaffected"}) from None
