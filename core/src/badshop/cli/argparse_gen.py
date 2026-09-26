"""Build argparse subcommands from tool parameter models."""

import argparse
import types
import typing
from typing import Any, Literal

from badshop.tools.registry import ToolSpec

METAVARS = {2: ("X", "Y"), 3: ("X", "Y", "R"), 4: ("X1", "Y1", "X2", "Y2")}


def _unwrap(t: Any) -> Any:
    """Strip Annotated and Optional wrappers."""
    while True:
        if typing.get_origin(t) is typing.Annotated:
            t = typing.get_args(t)[0]
        elif typing.get_origin(t) in (typing.Union, types.UnionType):
            args = [a for a in typing.get_args(t) if a is not type(None)]
            t = args[0]
        else:
            return t


def _classify(annotation: Any) -> tuple[str, Any]:
    t = _unwrap(annotation)
    origin = typing.get_origin(t)
    if t is bool:
        return "bool", None
    if origin is Literal:
        return "choice", list(typing.get_args(t))
    if origin is tuple:
        return "tuple", len(typing.get_args(t))
    if origin is list:
        kind, inner = _classify(typing.get_args(t)[0])
        return "list_" + kind, inner
    return "scalar", t


def _optional(annotation: Any) -> bool:
    return typing.get_origin(annotation) in (typing.Union, types.UnionType) and type(None) in typing.get_args(annotation)


def add_tool_parser(sub: argparse._SubParsersAction, spec: ToolSpec) -> None:
    model = spec.params
    # argparse %-formats help strings (e.g. "%(default)s"), so a literal % must be doubled there.
    s = sub.add_parser(spec.name, help=spec.summary.replace("%", "%%"), description=spec.summary)
    for name, f in model.model_fields.items():
        kind, inner = _classify(f.annotation)
        kw: dict[str, Any] = {"help": (f.description or "").replace("%", "%%"), "default": argparse.SUPPRESS}
        if kind == "choice":
            kw.update(choices=inner, type=type(inner[0]))
        elif kind == "list_choice":
            kw.update(choices=inner, type=type(inner[0]))
        elif kind == "tuple":
            kw.update(type=int, nargs=inner, metavar=METAVARS[inner])
        elif kind == "list_tuple":
            kw.update(type=int, nargs=inner, metavar=METAVARS[inner], action="append")
        elif kind == "list_scalar":
            kw.update(type=inner)
        elif kind == "scalar":
            kw.update(type=inner)
        if name in model.POSITIONAL:
            if kind.startswith("list_"):
                kw["nargs"] = "+" if f.is_required() else "*"
                kw.pop("action", None)
                if not f.is_required():
                    # argparse checks a non-None `*` default against `choices`; None parses to [].
                    kw["default"] = None
            elif _optional(f.annotation):
                kw["nargs"] = "?"
            s.add_argument(name, **kw)
            continue
        flag = model.FLAGS.get(name, "--" + name.replace("_", "-"))
        if kind == "bool":
            s.add_argument(flag, dest=name, action="store_true", help=kw["help"], default=argparse.SUPPRESS)
        else:
            if kind in ("list_scalar", "list_choice"):
                kw["action"] = "append"
            s.add_argument(flag, dest=name, required=f.is_required(), **kw)
    if spec.mutates:
        s.add_argument("-o", "--out", dest="_out", default=None, metavar="OUT",
                       help="path for the main output")
    s.set_defaults(_tool=spec.name)
