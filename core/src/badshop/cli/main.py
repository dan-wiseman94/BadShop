"""`badshop` command line: one subcommand per registered tool."""

import argparse
import sys
from pathlib import Path

from badshop import __version__
from badshop.cli import chat, recipes
from badshop.cli.argparse_gen import add_tool_parser
from badshop.cli.filestore import FileStore
from badshop.engine.errors import EngineError
from badshop.files import default_output_dir
from badshop.tools import REGISTRY
from badshop.tools.runner import run_tool

WORK_DIR = Path("badshop_work")


def final_dir() -> Path:
    return default_output_dir()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="badshop", description="Deliberately bad, old-internet photoshops.")
    p.add_argument("--version", action="version", version=f"badshop {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    for spec in REGISTRY.values():
        add_tool_parser(sub, spec)
    recipes.add_parsers(sub)
    chat.add_parser(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    if a.cmd == "chat":
        return chat.run_command(a)
    if a.cmd in recipes.RECIPE_COMMANDS:
        return recipes.run_command(a, main)
    raw = {k: v for k, v in vars(a).items() if k not in ("cmd", "_tool", "_out")}
    store = FileStore(WORK_DIR, final_dir(), getattr(a, "_out", None))
    try:
        run = run_tool(a._tool, raw, store)
    except EngineError as e:
        print(e.message, file=sys.stderr)
        if e.hint:
            print(f"hint: {e.hint}", file=sys.stderr)
        return 1
    for ref, out in zip(run.refs, run.result.outputs):
        print(f"{out.key}: {ref}" + (f" {out.caption}" if out.caption else ""))
    for line in run.result.lines:
        print(line)
    recipes.record(argv)
    return 0
