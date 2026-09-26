from dataclasses import dataclass
from pathlib import PurePath

from pydantic import ValidationError

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params
from badshop.tools.context import Store
from badshop.tools.registry import get, image_fields


@dataclass
class ToolRun:
    tool: str
    params: Params
    refs: list[str]  # stored outputs, same order as result.outputs
    result: EngineResult


def _explain(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'params'}: {err['msg']}" for err in e.errors())


def _stem(params: Params) -> str:
    for name, is_list in image_fields(type(params)).items():
        value = getattr(params, name)
        if is_list and value:
            value = value[0]
        if value:
            return PurePath(str(value)).stem
    return ""


def run_tool(name: str, raw: dict, store: Store) -> ToolRun:
    spec = get(name)
    try:
        params = spec.params.model_validate(raw)
    except ValidationError as e:
        raise EngineError(f"bad parameters for {name}", hint=_explain(e)) from None
    result = spec.run(params, store)
    stem = _stem(params)
    refs = [store.put(o, stem) for o in result.outputs]
    return ToolRun(name, params, refs, result)
