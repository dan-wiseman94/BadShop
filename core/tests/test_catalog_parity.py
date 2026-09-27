"""Every reference command and flag must exist in the new CLI."""

import argparse
import importlib.util

import pytest

from badshop.cli.main import build_parser
from badshop.tools import REGISTRY
from badshop.tools.registry import image_fields
from conftest import REFERENCE


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


@pytest.fixture(scope="module")
def reference_parser() -> argparse.ArgumentParser:
    spec = importlib.util.spec_from_file_location("reference_badshop", REFERENCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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
        spec.params.model_json_schema()  # must not raise
        for field in image_fields(spec.params):
            assert field in spec.params.model_fields
