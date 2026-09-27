import argparse
import shutil
from pathlib import Path
from typing import ClassVar, Literal

import pytest
from PIL import Image
from pydantic import Field

from badshop.cli import main as cli
from badshop.cli.argparse_gen import add_tool_parser
from badshop.cli.filestore import FileStore
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, ImageRef, Params
from badshop.tools import REGISTRY
from badshop.tools.registry import ToolSpec


def test_info_parity(pair):
    assert pair.new("info", "lincoln.png").stdout == pair.ref("info", "lincoln.png").stdout


def test_prep_parity(pair):
    assert pair.new("prep", "lincoln.png").stdout == pair.ref("prep", "lincoln.png").stdout
    pair.assert_same("badshop_work/lincoln_work.png")
    pair.assert_same("badshop_work/lincoln_work_grid.png")


@pytest.mark.parametrize("out", ["small.png", "small.jpg"])
def test_prep_out_parity(pair, out):
    stdout = pair.check("prep", "trump.png", "--max", "300", "-o", out, files=[out, "small_grid.png"])
    assert stdout == f"work: {out}\ngrid: small_grid.png\nsize: 237x300\n"


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


def test_out_parent_is_a_file_is_a_clean_error(pair):
    p = pair.new("prep", "lincoln.png", "-o", "lincoln.png/x.png", check=False)
    assert p.returncode == 1
    assert "can't write lincoln.png/x.png" in p.stderr and "hint:" in p.stderr
    assert "Traceback" not in p.stderr


def _anim() -> Output:
    frames = [Image.new("RGB", (8, 8), c).quantize(colors=4) for c in ("red", "blue")]
    return Output("animated", frames[0], "final:{stem}_spin", fmt="GIF", frames=frames, duration=100)


def test_out_animation_follows_suffix(tmp_path):
    out = _anim()
    png = FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "a.png")).put(out, "x")
    with Image.open(png) as im:
        assert im.format == "PNG" and im.n_frames == 2
    gif = FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "a.gif")).put(out, "x")
    assert Path(gif).read_bytes() == out.encode()


def test_out_unwritable_format_is_a_clean_error(tmp_path):
    rgba = Output("result", Image.new("RGBA", (8, 8)), "{stem}_work.png")
    with pytest.raises(EngineError, match="can't write x.jpg") as e:
        FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "x.jpg")).put(rgba, "x")
    assert e.value.hint == "use a .png name (PNG keeps transparency)"
    assert not (tmp_path / "x.jpg").exists()
    with pytest.raises(EngineError, match="can't write a.jpg"):  # JPEG can't hold an animation
        FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "a.jpg")).put(_anim(), "x")
    assert not (tmp_path / "a.jpg").exists()


def test_filesystem_failures_are_clean_errors(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a regular file where a folder should be")
    (tmp_path / "taken.png").mkdir()
    src = tmp_path / "src.png"
    Image.new("RGB", (8, 8)).save(src)
    work = Output("result", Image.new("RGB", (8, 8)), "{stem}_work.png")
    final = Output("saved", Image.new("RGB", (8, 8)), "final:{stem}_saved", fmt="JPEG", quality=90)
    attempts = [
        lambda: FileStore(blocker / "work", tmp_path / "f").put(work, "x"),  # work folder can't be made
        lambda: FileStore(tmp_path / "w", blocker / "final").put(final, "x"),  # $BADSHOP_OUT can't be made
        lambda: FileStore(tmp_path / "w", blocker / "final").export(str(src), None),
        lambda: FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "taken.png")).put(work, "x"),
    ]
    for attempt in attempts:
        with pytest.raises(EngineError, match="can't write") as e:
            attempt()
        assert e.value.hint == "check the folder exists and is writable"


def test_filestore_errors_have_hints(tmp_path):
    notes = tmp_path / "notes.png"
    notes.write_text("not an image")
    store = FileStore(tmp_path / "w", tmp_path / "f")
    with pytest.raises(EngineError, match="isn't an image") as e:
        store.load(str(notes))
    assert e.value.hint == "use a PNG, JPEG, GIF or WebP file"
    with pytest.raises(EngineError, match="no such image") as e:
        store.export(str(tmp_path / "missing.png"), None)
    assert e.value.hint == "check the path; outputs are printed as `key: path` lines"


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
    with pytest.raises(SystemExit) as e:
        _fake_parser().parse_args(["fake", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "30% too big" in out and "-o OUT" in out
    assert "100% fake" in _fake_parser().format_help()


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_tool_renders_help(name, capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args([name, "--help"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: badshop {name}")


def _colour(i: int) -> Output:
    return Output("emoji", Image.new("RGBA", (4, 4), ("red", "lime", "blue")[i]), "fetch/emoji_1f602.png")


def test_out_with_repeated_keys_keeps_every_output(tmp_path):
    # emoji a b c -o e.png: every output has the key "emoji", so the secondary names collided.
    store = FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "e.png"))
    paths = [store.put(_colour(i), "x") for i in range(3)]
    assert paths == [str(tmp_path / n) for n in ("e.png", "e_emoji.png", "e_emoji_2.png")]
    for path, rgb in zip(paths, [(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        with Image.open(path) as im:
            assert im.convert("RGB").getpixel((0, 0)) == rgb


def test_one_run_never_writes_a_path_twice(tmp_path):
    store = FileStore(tmp_path / "w", tmp_path / "f")
    paths = [store.put(_colour(i), "x") for i in range(3)]
    assert paths == [str(tmp_path / "w/fetch" / n) for n in ("emoji_1f602.png", "emoji_1f602_2.png", "emoji_1f602_3.png")]
    # a new run (a new store) writes the usual name again, as the reference does
    assert FileStore(tmp_path / "w", tmp_path / "f").put(_colour(0), "x") == paths[0]


def test_unique_secondary_names_are_unchanged(tmp_path):
    store = FileStore(tmp_path / "w", tmp_path / "f", str(tmp_path / "small.png"))
    store.put(Output("work", Image.new("RGB", (4, 4)), "{stem}_work.png"), "x")
    assert store.put(Output("grid", Image.new("RGB", (4, 4)), "{stem}_work_grid.png"), "x") == str(tmp_path / "small_grid.png")
