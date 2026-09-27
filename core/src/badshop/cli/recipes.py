"""CLI-only `recipe` and `run`: turn the command history into a replayable recipe, and replay it.

Ported from reference/badshop.py (the recipes section).
"""

import argparse
import contextlib
import io
import json
import re
import shlex
import sys
import time
from collections.abc import Callable
from pathlib import Path, PurePath

from badshop.tools import REGISTRY

HISTORY = Path("badshop_work") / "history.jsonl"
RECIPE_COMMANDS = {"recipe", "run"}
REPLAYING = False  # `run` turns this on so replays don't re-log themselves


def output_of(argv: list[str]) -> str | None:
    for flag in ("-o", "--out"):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return argv[argv.index(flag) + 1]
    return None


def record(argv: list[str]) -> None:
    """Log a successful editing command. Looking (read_only) and fetching (network) tools are not logged."""
    if REPLAYING or argv[0] in RECIPE_COMMANDS:
        return
    spec = REGISTRY.get(argv[0])  # None for `badshop -- text ...`, which argparse accepts
    if spec is None or spec.read_only or spec.network:
        return
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as fh:
        fh.write(json.dumps({"argv": argv, "time": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")


class _Damaged(Exception):
    pass


def _read_history() -> list[dict]:
    """The logged commands. A line that isn't one (a crash mid-write, a hand edit) raises _Damaged."""
    if not HISTORY.exists():
        return []
    entries = []
    for n, line in enumerate(HISTORY.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError as err:
            raise _Damaged(f"{HISTORY} line {n} is damaged ({err})") from None
        argv = e.get("argv") if isinstance(e, dict) else None
        if not (isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv)):
            raise _Damaged(f"{HISTORY} line {n} is damaged (not a logged command)")
        entries.append(e)
    return entries


def cmd_recipe(a: argparse.Namespace) -> int:
    if a.clear:
        HISTORY.unlink(missing_ok=True)
        print(f"cleared: {HISTORY}")
        return 0
    try:
        entries = _read_history()
    except (_Damaged, OSError, UnicodeDecodeError) as e:
        print(f"{e}; fix it or run recipe --clear", file=sys.stderr)
        return 1
    if a.last:
        entries = entries[-a.last:]
    if not entries:
        print(f"no history in {HISTORY} yet; run some editing commands first", file=sys.stderr)
        return 1
    # A re-run that writes the same -o file replaces the earlier attempt but keeps its place in line,
    # so the corrections made along the way collapse into one clean pipeline.
    slots, order = {}, []
    for i, e in enumerate(entries):
        key = output_of(e["argv"]) or f"#{i}"
        if key not in slots:
            order.append(key)
        slots[key] = e["argv"]
    steps = [slots[k] for k in order]
    out = Path(a.out) if a.out else HISTORY.parent / "recipe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"vars": {}, "steps": steps}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"recipe: {out}")
    print(f"{len(steps)} step(s) from {len(entries)} logged command(s)")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {shlex.join(s)}")
    print('to parametrize: put "{name}" in any argument and add name to "vars", then `run --set name=value`')
    return 0


def _is_recipe(data) -> bool:
    def scalar(x):
        return type(x) in (str, int, float)
    return (isinstance(data, dict) and isinstance(data.get("vars", {}), dict)
            and all(scalar(v) for v in data.get("vars", {}).values())
            and isinstance(data.get("steps"), list)
            and all(isinstance(s, list) and s and all(map(scalar, s)) for s in data["steps"]))


def _outside(path: str) -> bool:
    p = PurePath(path)
    return bool(p.anchor) or ".." in p.parts


def _step_problem(argv: list[str], allow_outside: bool, parser: argparse.ArgumentParser) -> str | None:
    """Why a recipe step must not run, or None. Checked for every step before any runs: a recipe is data
    someone may have shared, so it may only run badshop tools and, unless allowed, write below this folder."""
    if argv[0] not in REGISTRY:  # never `run` or `recipe`, so a recipe can't replay itself
        return f"isn't a badshop tool: {argv[0]}"
    if allow_outside:
        return None
    try:  # the real parser, so -o X, --out=X, -oX and --ou X are all seen
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            out = getattr(parser.parse_args(argv), "_out", None)
    except SystemExit:
        return None  # argparse rejects the step: it fails at its turn, as it always did (rc 2)
    if out is not None and _outside(out):
        return f"writes outside this folder: {out}"
    return None


def cmd_run(a: argparse.Namespace, main: Callable[[list[str]], int]) -> int:
    global REPLAYING
    try:
        data = json.loads(Path(a.recipe).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"can't read recipe {a.recipe} ({e})", file=sys.stderr)
        return 1
    if not _is_recipe(data):
        print(f'{a.recipe} isn\'t a recipe: want {{"vars": {{"name": "value"}}, '
              f'"steps": [["command", "arg", ...], ...]}}', file=sys.stderr)
        return 1
    variables = {k: str(v) for k, v in data.get("vars", {}).items()}
    for s in a.set or []:
        k, sep, v = s.partition("=")
        if not sep:
            print(f"--set wants name=value, got {s!r}", file=sys.stderr)
            return 1
        variables[k] = v
    steps = data["steps"]

    def fill(arg):
        return re.sub(r"\{(\w+)\}", lambda m: variables.get(m.group(1), m.group(0)), str(arg))

    from badshop.cli.main import build_parser  # main imports this module

    steps, parser = [[fill(x) for x in argv] for argv in steps], build_parser()
    for i, argv in enumerate(steps, 1):
        problem = _step_problem(argv, a.allow_outside, parser)
        if problem:
            print(f"recipe step {i} {problem}", file=sys.stderr)
            if problem.startswith("writes"):
                print("hint: nothing ran; if you trust this recipe, run it again with --allow-outside",
                      file=sys.stderr)
            else:
                print("hint: nothing ran; each step starts with a tool name, like text or paste", file=sys.stderr)
            return 1
    previous, REPLAYING = REPLAYING, True
    try:
        for i, argv in enumerate(steps, 1):
            if i < a.from_step:
                continue
            print(f"== step {i}/{len(steps)}: {shlex.join(argv)}")
            try:
                rc = main(argv)
            except SystemExit as e:  # an argparse error (or --help) inside a replayed step
                rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            if rc != 0:
                print(f"step {i} failed", file=sys.stderr)
                return rc
    finally:
        REPLAYING = previous
    return 0


def add_parsers(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("recipe", help="write the logged editing commands as a replayable recipe")
    s.add_argument("--last", type=int, help="only use the last N logged commands")
    s.add_argument("--clear", action="store_true", help="forget the history (do this before starting a new meme)")
    s.add_argument("-o", "--out", help="default badshop_work/recipe.json")
    s.set_defaults(_recipe=lambda a, main: cmd_recipe(a))

    s = sub.add_parser("run", help="replay a recipe")
    s.add_argument("recipe")
    s.add_argument("--set", action="append", metavar="NAME=VALUE", help='fill "{NAME}" in the recipe; repeatable')
    s.add_argument("--from", dest="from_step", type=int, default=1, help="start at this step number")
    s.add_argument("--allow-outside", action="store_true",
                   help="let steps write -o files outside this folder (absolute paths or ..)")
    s.set_defaults(_recipe=cmd_run)


def run_command(a: argparse.Namespace, main: Callable[[list[str]], int]) -> int:
    return a._recipe(a, main)
