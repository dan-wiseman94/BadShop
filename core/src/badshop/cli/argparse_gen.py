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
        details = []
        if not f.is_required():
            default = f.get_default(call_default_factory=True)
            if default is not None:
                details.append(f"default {default}")
        bounds = {key: getattr(meta, key) for meta in f.metadata
                  for key in ("ge", "le", "gt", "lt") if getattr(meta, key, None) is not None}
        if "ge" in bounds and "le" in bounds:
            details.append(f"{bounds['ge']}-{bounds['le']}")
        else:
            details.extend(f"{key} {value}" for key, value in bounds.items())
        help_text = (f.description or "") + (" (" + "; ".join(details) + ")" if details else "")
        kw: dict[str, Any] = {"help": help_text.replace("%", "%%"), "default": argparse.SUPPRESS}
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


def _plain(value: Any) -> Any:
    """Tuples as lists, so JSON params compare equal to a model's defaults."""
    return [_plain(v) for v in value] if isinstance(value, (list, tuple)) else value


def _option(flag: str, value: Any) -> list[str]:
    word = str(value)
    # argparse reads a word starting with "-" as the next option ("--rotate -1e-05", "--text -_-").
    return [f"{flag}={word}"] if word.startswith("-") else [flag, word]


def to_argv(spec: ToolSpec, params: dict) -> list[str]:
    """The command line (tool name first) that `add_tool_parser`'s parser reads back as `params`.

    `params` is a validated, JSON-safe dict such as a step's params. Positional fields come first, in
    POSITIONAL order, then flags in field order (FLAGS or --field-name). Fields missing from `params` or at
    their default are left out, tuples are spelled out, lists repeat their flag, and True bools are bare
    flags. A flag value starting with "-" is written --flag=value; positional values that start with "-"
    go after a "--", with every flag before it. One value depends on the Python reading it back: a word
    that is exactly "--". Python 3.12.11 and 3.13 keep it; older 3.12 releases drop it (a caption of "--"
    parses as text=[] on 3.12.0 and 3.12.5), which the tool then refuses as bad parameters."""
    model = spec.params
    positional: list[str] = []
    flags: list[str] = []
    for name, f in model.model_fields.items():
        if name not in params:
            continue
        value = _plain(params[name])
        if not f.is_required() and value == _plain(f.get_default(call_default_factory=True)):
            continue
        if name in model.POSITIONAL:
            positional += [str(v) for v in value] if isinstance(value, list) else [str(value)]
            continue
        kind, _ = _classify(f.annotation)
        flag = model.FLAGS.get(name, "--" + name.replace("_", "-"))
        if kind == "bool":
            if value is not True:  # store_true flags can only switch a False default on
                raise ValueError(f"{spec.name}: {name}={value!r} can't be written as a command-line flag")
            flags.append(flag)
        elif kind == "tuple":
            flags += [flag, *map(str, value)]  # whole numbers: "-5" is read as a value, not an option
        elif kind == "list_tuple":
            for item in value:
                flags += [flag, *map(str, item)]
        elif kind.startswith("list_"):
            for item in value:
                flags += _option(flag, item)
        else:
            flags += _option(flag, value)
    if any(word.startswith("-") for word in positional):
        return [spec.name, *flags, "--", *positional]
    return [spec.name, *positional, *flags]
