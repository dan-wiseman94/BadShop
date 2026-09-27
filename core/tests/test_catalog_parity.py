"""Every reference command and flag must exist in the new CLI."""

import argparse
import re
import shlex

import jsonschema
import pytest

from badshop.cli.main import build_parser
from badshop.tools import REGISTRY
from badshop.tools.registry import image_fields, llm_schema
from conftest import REFERENCE, load_reference
from test_params import BASE


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


@pytest.fixture(scope="module")
def reference_parser() -> argparse.ArgumentParser:
    mod = load_reference()
    captured = {}
    original = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        captured["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = grab
    try:
        mod.main(["info", "x"])
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    return captured["p"]


def test_every_reference_command_exists(reference_parser):
    new = _subparsers(build_parser())
    assert set(_subparsers(reference_parser)) <= set(new)


def test_every_reference_flag_and_positional_exists(reference_parser):
    new = _subparsers(build_parser())
    for name, ref_sub in _subparsers(reference_parser).items():
        ref_opts = {o for a in ref_sub._actions for o in a.option_strings}
        new_opts = {o for a in new[name]._actions for o in a.option_strings}
        assert ref_opts <= new_opts, f"{name}: missing {ref_opts - new_opts}"
        ref_pos = [a.dest for a in ref_sub._actions if not a.option_strings]
        new_pos = [a.dest for a in new[name]._actions if not a.option_strings]
        assert ref_pos == new_pos, f"{name}: positionals {new_pos} != {ref_pos}"


def test_registry_is_complete_and_described():
    engine_tools = {"prep", "fetch", "wiki", "emoji", "template", "find", "cutout", "paste", "text", "draw",
                    "censor", "eyes", "warp", "flare", "sparkle", "watermark", "filter", "save", "deepfry",
                    "animate", "info"}
    assert set(REGISTRY) == engine_tools | {"view", "export"}
    for spec in REGISTRY.values():
        assert len(spec.description) >= 40, spec.name


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_schema_is_valid_json_schema(name):
    # Spec 11: the schema a model (or a UI form) receives must be a real JSON Schema, not merely one
    # pydantic can print. Pydantic writes draft 2020-12.
    schema = llm_schema(REGISTRY[name])
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(REGISTRY[name].params.model_validate(BASE[name]).model_dump(mode="json"))


# (mutates, network, read_only): the approval gate (spec 7) and the recipe log rely on these.
FLAGS = {
    **{n: (True, True, False) for n in ("fetch", "wiki", "emoji", "template")},
    **{n: (False, False, True) for n in ("info", "view", "find")},
    "export": (False, False, False),
    **{n: (True, False, False) for n in ("prep", "text", "cutout", "paste", "draw", "censor", "eyes", "filter",
                                         "warp", "flare", "sparkle", "watermark", "save", "deepfry", "animate")},
}


def test_tool_flags_are_pinned():
    assert {n: (s.mutates, s.network, s.read_only) for n, s in REGISTRY.items()} == FLAGS


# The fields sessions resolve as images (and whether they hold a list); Plan 2 remaps them on replay.
IMAGE_FIELDS = {
    **{n: {} for n in ("fetch", "wiki", "emoji", "template")},
    "paste": {"base": False, "piece": False}, "animate": {"images": True},
    **{n: {"image": False} for n in ("info", "prep", "view", "find", "text", "cutout", "draw", "censor", "eyes",
                                     "filter", "warp", "flare", "sparkle", "watermark", "save", "deepfry", "export")},
}

IMAGE, POINT, BOX, SPOT, COLOR, SEED = "badshop-image", "badshop-point", "badshop-box", "badshop-spot", "color", "badshop-seed"
# Every field's schema format: the UI picks its widget by it (spec 5.2), a model reads it as a type.
FORMATS = {
    **{n: {} for n in ("fetch", "wiki", "emoji", "template")},
    **{n: {"image": IMAGE} for n in ("info", "prep", "view", "find", "filter", "watermark", "save", "export")},
    "censor": {"image": IMAGE, "box": BOX},
    "text": {"image": IMAGE, "at": POINT, "color": COLOR},
    "cutout": {"image": IMAGE, "box": BOX, "sticker_color": COLOR},
    "paste": {"base": IMAGE, "piece": IMAGE, "at": POINT, "fit_box": BOX, "region": BOX, "seed": SEED},
    "draw": {"image": IMAGE, "circle": SPOT, "arrow": BOX, "line": BOX, "rect": BOX, "color": COLOR},
    "eyes": {"image": IMAGE, "at": POINT, "color": COLOR},
    "warp": {"image": IMAGE, "at": SPOT},
    "flare": {"image": IMAGE, "at": POINT},
    "sparkle": {"image": IMAGE, "at": POINT, "region": BOX, "color": COLOR, "seed": SEED},
    "deepfry": {"image": IMAGE, "seed": SEED},
    "animate": {"images": IMAGE, "at": POINT, "seed": SEED},
}


def _formats(prop: dict) -> set[str]:
    """The formats in a property's schema and every schema nested in it (anyOf branches, list items)."""
    found = {prop["format"]} if "format" in prop else set()
    for sub in prop.get("anyOf", []):
        found |= _formats(sub)
    if isinstance(prop.get("items"), dict):
        found |= _formats(prop["items"])
    return found


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_image_fields_and_formats_are_pinned(name):
    spec = REGISTRY[name]
    assert image_fields(spec.params) == IMAGE_FIELDS[name]
    formats = {field: _formats(prop) for field, prop in llm_schema(spec)["properties"].items()}
    assert {field: f.pop() for field, f in formats.items() if len(f) == 1} == FORMATS[name]
    assert all(len(f) == 0 for f in formats.values())  # none has two formats (pop() emptied the single ones)


# --- every invocation reference/SKILL.md shows still parses and validates (the Done-when's "unchanged") ---

SKILL = REFERENCE.parent / "SKILL.md"

# Each command span in SKILL.md with its placeholders filled in as the workflow would fill them.
SKILL_SPANS = {
    'wiki "Name"': 'wiki "Abraham Lincoln"',
    'fetch "words"': 'fetch "labrador retriever sitting"',
    "fetch URL": "fetch https://example.org/photo.jpg",
    "fetch --clipboard": "fetch --clipboard",
    "emoji 😂 skull 1f480 ...": "emoji 😂 skull 1f480 fire",
    'template "name"': 'template "distracted boyfriend"',
    "prep IMAGE": "prep lincoln.png",
    "find IMAGE": "find lincoln_work.png",
    "cutout IMAGE [--box X1 Y1 X2 Y2]": "cutout lincoln_work.png --box 52 0 362 333",
    "paste BASE PIECE": "paste trump_work.png lincoln_work_cutout.png",
    'text IMAGE "words"': 'text result.png "you had one job"',
    "draw IMAGE": "draw result.png",
    "censor IMAGE --box X1 Y1 X2 Y2": "censor result.png --box 160 170 250 195",
    "eyes IMAGE --at X Y --at X Y": "eyes result.png --at 165 182 --at 243 179",
    "warp IMAGE --at X Y R": "warp result.png --at 165 182 31",
    "flare IMAGE --at X Y": "flare result.png --at 480 90",
    "sparkle IMAGE": "sparkle result.png",
    "watermark IMAGE hypercam bandicam ifunny mematic": "watermark result.png hypercam bandicam ifunny mematic",
    "filter IMAGE NAME...": "filter result.png emboss solarize",
    "info IMAGE": "info result.png",
    "save IMAGE": "save result.png",
    "deepfry IMAGE": "deepfry result.png",
    "animate IMAGE [IMAGE...]": "animate lasers.png plain.png",
    "run recipe.json": "run badshop_work/recipe.json",
    "recipe --clear": "recipe --clear",
    'wiki "Name" -n 2': 'wiki "Nicolas Cage" -n 2',
    "cutout --box <head box>": "cutout lincoln_work.png --box 52 0 362 333",
    "cutout --oval --box <oval box>": "cutout lincoln_work.png --oval --box 117 123 296 310",
    "paste --fit-box <target head box> --scale 1.1": "paste trump_work.png lincoln_work_cutout.png --fit-box 60 10 380 360 --scale 1.1",
    "paste --repeat": "paste result.png emoji_1f602.png --repeat 25 --width 60",
    "run --set": 'run badshop_work/recipe.json --set "caption=NEW WORDS"',
    "warp --strength 1": "warp result.png --at 165 182 31 --strength 1",
    "save --quality 15 --passes 3": "save result.png --quality 15 --passes 3 --name lincoln_worse",
    "save --lowres 0.25": "save result.png --lowres 0.25",
    "deepfry --level 5": "deepfry result.png --level 5 --name nuked",
    "animate --effect zoom --fry 5": "animate result.png --effect zoom --fry 5 --name zoomfry",
}

# Every flag and value the command tables and the recipe notes describe, in use.
SKILL_FLAGS = [
    'fetch "mona lisa painting" --source commons -n 3', 'fetch "sad businessman" --source openverse',
    "emoji 😂 --size 144", "template drake -n 2", "template --list",
    "find lincoln_work.png --what cats --min-score 0.3",
    "cutout lincoln_work.png --box 52 0 362 333 --model u2net_human_seg --sticker 8 --sticker-color yellow",
    "cutout lincoln_work.png --grow 6 --no-ai", "cutout toon.png --model isnet-anime",
    "paste base.png piece.png --at 300 580 --width 200 --anchor bottom --height 120 --rotate 12 --flip",
    "paste base.png piece.png --at 300 300 --width 200 --anchor center",
    "paste base.png piece.png --at 10 10 --width 90 --anchor topleft",
    "paste base.png piece.png --repeat 40 --width 60 --region 0 600 661 1000 --seed 3",
    'text x.png "leonardo" --bottom', 'text x.png "Four score and\\nseven" --style wordart --color purple',
    'text x.png "hand drawn" --style paint --color blue --rotate 10 --at 300 400',
    "draw x.png --circle 300 250 80 --arrow 550 550 350 350 --line 0 0 100 100 --rect 10 10 200 120 --color red --width 6",
    "censor x.png --box 1 1 50 50 --style pixelate --block 5", "censor x.png --box 1 1 50 50 --style bar",
    "censor x.png --box 1 1 50 50 --box 60 60 90 90 --style blur",
    "eyes x.png --at 260 240 --angle 30 --size 9 --color cyan",
    "flare x.png --at 100 500 --size 40",
    "sparkle x.png --at 100 100 --at 200 150 --size 30 --color #88f",
    "sparkle x.png --repeat 12 --region 20 300 400 580",
    'watermark x.png --text "made in badshop" --corner br',
    "save x.png --gif --colors 16", "deepfry x.png --level 1 --no-tint",
    "animate a.png --effect shake --amount 12 --delay 60", "animate a.png --effect flash",
    "animate a.png --effect zoom --at 300 250 --amount 2.5", "animate a.png --effect spin",
    "run badshop_work/recipe.json --from 2",
]


def _skill_spans() -> list[str]:
    """Every code span in SKILL.md that is a command with arguments (a bare `save` is a mention)."""
    commands = set(REGISTRY) | {"recipe", "run"}
    spans = re.findall(r"`([^`\n]+)`", SKILL.read_text())
    return list(dict.fromkeys(s for s in spans if len(s.split()) > 1 and s.split()[0] in commands))


def test_every_skill_invocation_is_listed():
    assert _skill_spans() == list(SKILL_SPANS)


def _skill_rows() -> dict[str, set[str]]:
    """The flags each command-table row of SKILL.md mentions, by command."""
    rows: dict[str, set[str]] = {}
    for row in SKILL.read_text().splitlines():
        if row.startswith("| `") and not row.startswith("| `Command"):
            command = row.split("`")[1].split()[0]
            rows.setdefault(command, set()).update(re.findall(r"(?<![\w-])(--?[a-z][a-z0-9-]*)", row))
    return rows


def _parsed(line: str) -> tuple[str, argparse.Namespace]:
    argv = shlex.split(line)
    return argv[0], build_parser().parse_args(argv)


@pytest.mark.parametrize("line", [*SKILL_SPANS.values(), *SKILL_FLAGS])
def test_skill_invocations_parse_and_validate(line):
    command, a = _parsed(line)
    if command in REGISTRY:  # recipe and run are CLI-only: parsing is their whole contract
        REGISTRY[command].params.model_validate({k: v for k, v in vars(a).items() if k not in ("cmd", "_tool", "_out")})


def test_every_flag_skill_documents_is_exercised():
    used: dict[str, set[str]] = {}
    for line in [*SKILL_SPANS.values(), *SKILL_FLAGS]:
        argv = shlex.split(line)
        used.setdefault(argv[0], set()).update(a for a in argv[1:] if re.fullmatch(r"--?[a-z][a-z0-9-]*", a))
    rows = _skill_rows()
    assert set(rows) == set(REGISTRY) - {"view", "export"}  # the reference's 21 tools, one row each
    for command, flags in rows.items():
        assert flags <= used.get(command, set()), f"{command}: {flags - used.get(command, set())}"
