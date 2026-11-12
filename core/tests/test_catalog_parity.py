"""Every reference command and flag must exist in the new CLI."""

import argparse

import jsonschema
import pytest

from badshop.cli.main import build_parser
from badshop.tools import REGISTRY
from badshop.tools.registry import llm_schema, ui_schema, user_only_fields
from conftest import load_reference
from test_params import BASE
RETRO_TOOLS = {'retro_layout', 'canvas', 'pattern', 'palette', 'bitmap_text', 'animate_sticker', 'export_profile', 'collection_items'}


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
    assert set(REGISTRY) == engine_tools | {"view", "export", "discover", "acquire", "layout", "pair_images", "slice_sheet", "transform"} | RETRO_TOOLS
    for spec in REGISTRY.values():
        assert len(spec.description) >= 40, spec.name


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_schema_is_valid_json_schema(name):
    # Spec 11: the schemas a UI form and a model receive must be real JSON Schemas, not merely ones
    # pydantic can print. Pydantic writes draft 2020-12. The model's schema has no user-only fields.
    spec = REGISTRY[name]
    dumped = spec.params.model_validate(BASE[name]).model_dump(mode="json")
    hidden = user_only_fields(spec.params)
    for schema, params in ((ui_schema(spec), dumped),
                           (llm_schema(spec), {k: v for k, v in dumped.items() if k not in hidden})):
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(params)


# (mutates, network, read_only, writes_files): the approval gate (spec 7), the recipe log and the
# session's in-process export rely on these.
FLAGS = {
    "transform": (True, False, False, False),
    **{n: (True, False, False, False) for n in RETRO_TOOLS - {'collection_items'}},
    'collection_items': (False, True, False, False),
    "layout": (True, False, False, False),
    "pair_images": (True, False, False, False),
    "slice_sheet": (True, False, False, False),
    "discover": (True, True, False, False),
    **{n: (True, True, False, False) for n in ("fetch", "wiki", "emoji", "template", "acquire")},
    **{n: (False, False, True, False) for n in ("info", "view", "find")},
    "export": (False, False, False, True),
    **{n: (True, False, False, False) for n in ("prep", "text", "cutout", "paste", "draw", "censor", "eyes",
                                                "filter", "warp", "flare", "sparkle", "watermark", "save",
                                                "deepfry", "animate")},
}


def test_tool_flags_are_pinned():
    assert {n: (s.mutates, s.network, s.read_only, s.writes_files) for n, s in REGISTRY.items()} == FLAGS
