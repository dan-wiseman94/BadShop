from dataclasses import dataclass
from pathlib import PurePath

from pydantic import ValidationError

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params
from badshop.tools.context import Store
from badshop.tools.registry import get, image_fields, user_only_fields


@dataclass
class ToolRun:
    tool: str
    params: Params
    refs: list[str]  # stored outputs, same order as result.outputs
    result: EngineResult


def is_trusted(actor: str) -> bool:
    """Only the user ("user": the UI or the CLI) is trusted; a model ("agent:<provider>") or a CLI agent
    ("cli:<name>") is not, whatever it claims."""
    return actor == "user"


def explain(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'params'}: {err['msg']}" for err in e.errors())


def _stem(params: Params) -> str:
    for name, is_list in image_fields(type(params)).items():
        value = getattr(params, name)
        if is_list and value:
            value = value[0]
        if value:
            return PurePath(str(value)).stem
    return ""


def validate(name: str, raw: dict, actor: str = "user") -> Params:
    """Check a call's parameters without running it (the approval gate shows them and lets the user edit
    them first). Any actor but the user must leave user-only fields at their defaults."""
    spec = get(name)
    try:
        params = spec.params.model_validate(raw)
    except ValidationError as e:
        raise EngineError(f"bad parameters for {name}", hint=explain(e)) from None
    if not is_trusted(actor):
        if name == "text" and params.font is not None:
            from badshop.tools.fonts import font_names
            if params.font not in font_names():
                raise EngineError("text: choose a discovered font name",
                                  hint="omit font for the style default; only the user can pick a file path")
        hidden = user_only_fields(spec.params)
        for field, info in spec.params.model_fields.items():  # declaration order: the first one is named
            if field in hidden and getattr(params, field) != info.get_default(call_default_factory=True):
                raise EngineError(f"{name}: {field} can only be set by the user",
                                  hint=f"leave {field} out, or ask the user to do it in the app")
    return params


def execute(name: str, params: Params, store: Store, stem: str | None = None) -> ToolRun:
    """Run validated parameters and put every output in the store, named from `stem` (`{stem}_work.png`).
    None takes the stem from the first image ref, as the CLI always has."""
    spec = get(name)
    if not isinstance(params, spec.params):
        raise TypeError(f"{name} takes {spec.params.__name__}, not {type(params).__name__}")
    result = spec.run(params, store)
    stem = _stem(params) if stem is None else stem
    refs = [store.put(o, stem) for o in result.outputs]
    return ToolRun(name, params, refs, result)


def run_tool(name: str, raw: dict, store: Store, actor: str = "user") -> ToolRun:
    """Validate, then run: the CLI's path, and any caller with no approval step in between."""
    return execute(name, validate(name, raw, actor), store)
