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


def _format(extra: Any) -> str | None:
    return extra.get("format") if isinstance(extra, dict) else None  # coordinate types use a schema hook


def _is_image(annotation: Any) -> bool:
    return any(_format(getattr(meta, "json_schema_extra", None)) == "badshop-image"
               for meta in getattr(annotation, "__metadata__", ()))


def image_fields(params_cls: type[Params]) -> dict[str, bool]:
    """Fields holding image references -> whether the field is a list of them."""
    found = {}
    for name, f in params_cls.model_fields.items():
        # A plain `x: ImageRef` field: pydantic merges the Annotated Field into the FieldInfo itself.
        if _format(f.json_schema_extra) == "badshop-image":
            found[name] = False
            continue
        # list[ImageRef] / ImageRef | None keep the Annotated wrapper inside the annotation.
        for arg in typing.get_args(f.annotation):  # list[ImageRef], Optional[ImageRef]
            if _is_image(arg):
                found[name] = typing.get_origin(f.annotation) is list
            elif typing.get_origin(arg) is list and any(map(_is_image, typing.get_args(arg))):
                found[name] = True  # Optional[list[ImageRef]]
    return found


def llm_schema(spec: ToolSpec) -> dict:
    return spec.params.model_json_schema()
