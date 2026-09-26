import argparse
import shutil
from typing import ClassVar, Literal

import pytest
from PIL import Image
from pydantic import Field

from badshop.cli import main as cli
from badshop.cli.argparse_gen import add_tool_parser
from badshop.engine.result import EngineResult
from badshop.engine.types import Box, ImageRef, Params
from badshop.tools import REGISTRY
from badshop.tools.registry import ToolSpec


def test_info_parity(pair):
    assert pair.new("info", "lincoln.png").stdout == pair.ref("info", "lincoln.png").stdout


def test_prep_parity(pair):
    assert pair.new("prep", "lincoln.png").stdout == pair.ref("prep", "lincoln.png").stdout
    pair.assert_same("badshop_work/lincoln_work.png")
    pair.assert_same("badshop_work/lincoln_work_grid.png")


def test_prep_out_parity(pair):
    pair.ref("prep", "trump.png", "--max", "300", "-o", "small.png")
    pair.new("prep", "trump.png", "--max", "300", "-o", "small.png")
    pair.assert_same("small.png")
    pair.assert_same("small_grid.png")


def test_prep_out_jpg_parity(pair):
    pair.ref("prep", "trump.png", "--max", "300", "-o", "small.jpg")
    pair.new("prep", "trump.png", "--max", "300", "-o", "small.jpg")
    pair.assert_same("small.jpg")
    pair.assert_same("small_grid.png")


def test_prep_huge_image(pair):
    Image.new("RGB", (6000, 4000), "gray").save(pair.new_dir / "phone.jpg")
    out = pair.new("prep", "phone.jpg").stdout
    assert "size: 1000x667" in out


def test_info_path_with_spaces(pair):
    shutil.copy(pair.new_dir / "lincoln.png", pair.new_dir / "old photo é.png")
    out = pair.new("info", "old photo é.png").stdout
    assert out.startswith("old photo é.png: ")


def test_missing_file_is_a_clean_error(pair):
    p = pair.new("info", "missing.png", check=False)
    assert p.returncode == 1
    assert "no such image: missing.png" in p.stderr and "hint:" in p.stderr
    assert "Traceback" not in p.stderr


def test_bad_value_is_a_clean_error(pair):
    p = pair.new("prep", "lincoln.png", "--max", "3", check=False)
    assert p.returncode == 1 and "max" in p.stderr and "Traceback" not in p.stderr


def test_help_lists_tools(pair):
    out = pair.new("--help").stdout
    for name in ("info", "prep", "view"):
        assert name in out


class _Fake(Params):
    POSITIONAL: ClassVar = ("image", "names")
    image: ImageRef
    names: list[Literal["hypercam", "ifunny"]] = []
    box: list[Box] = Field(description="a box; repeatable")
    scale: float = Field(1.0, description="1.3 = 30% too big")


def _fake_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="badshop")
    spec = ToolSpec(name="fake", params=_Fake, run=lambda p, s: EngineResult(), summary="100% fake",
                    description="a tool that only exists in this test", category="effects")
    add_tool_parser(p.add_subparsers(dest="cmd"), spec)
    return p


def test_generated_parser_edge_cases(capsys):
    a = _fake_parser().parse_args(["fake", "x.png", "--box", "1", "2", "3", "4"])
    assert a.names == [] and a.box == [[1, 2, 3, 4]] and a._out is None and a._tool == "fake"
    a = _fake_parser().parse_args(["fake", "x.png", "ifunny", "--box", "1", "2", "3", "4"])
    assert a.names == ["ifunny"]
    with pytest.raises(SystemExit) as e:  # a required flag is an argparse usage error, like the reference
        _fake_parser().parse_args(["fake", "x.png"])
    assert e.value.code == 2 and "--box" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _fake_parser().parse_args(["fake", "--help"])
    out = capsys.readouterr().out
    assert "30% too big" in out and "-o OUT" in out
    assert "100% fake" in _fake_parser().format_help()


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_tool_renders_help(name, capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args([name, "--help"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: badshop {name}")
