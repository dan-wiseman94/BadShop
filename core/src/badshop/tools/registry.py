"""The single list of tools. LLM tools, MCP, UI forms and the CLI are all generated from it."""

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: type[Params]
    run: Callable[[Any, Any], EngineResult]  # (params, store) -> result
    summary: str  # one line: CLI help, UI palette
    description: str  # for LLMs: what it does, when to use it, coordinate conventions
    category: str  # sources | inspect | cut | compose | text | effects | finish
    mutates: bool = True  # produces new images
    network: bool = False
    read_only: bool = False


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"tool {spec.name!r} is already registered")
    REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> ToolSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        raise EngineError(f"unknown tool {name!r}", hint=f"tools: {', '.join(sorted(REGISTRY))}") from None


def _is_image(annotation: Any) -> bool:
    for meta in getattr(annotation, "__metadata__", ()):
        extra = getattr(meta, "json_schema_extra", None) or {}
        if extra.get("format") == "badshop-image":
            return True
    return False


def image_fields(params_cls: type[Params]) -> dict[str, bool]:
    """Fields holding image references -> whether the field is a list of them."""
    found = {}
    for name, f in params_cls.model_fields.items():
        # A plain `x: ImageRef` field: pydantic merges the Annotated Field into the FieldInfo itself.
        if (f.json_schema_extra or {}).get("format") == "badshop-image":
            found[name] = False
            continue
        # list[ImageRef] / ImageRef | None keep the Annotated wrapper inside the annotation.
        for arg in typing.get_args(f.annotation):  # list[ImageRef], Optional[ImageRef]
            if _is_image(arg):
                found[name] = typing.get_origin(f.annotation) is list
    return found


def llm_schema(spec: ToolSpec) -> dict:
    return spec.params.model_json_schema()
