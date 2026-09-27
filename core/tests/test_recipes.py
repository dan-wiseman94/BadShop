import json
import shutil

import pytest

from badshop.cli import main as cli
from conftest import FIXTURES


def test_recipe_collapses_reruns_and_replays(pair):
    pair.new("recipe", "--clear")
    pair.new("text", "lincoln.png", "first try", "-o", "badshop_work/a.png")
    pair.new("text", "lincoln.png", "second try", "-o", "badshop_work/a.png")
    pair.new("eyes", "badshop_work/a.png", "--at", "260", "240", "-o", "badshop_work/b.png")
    pair.new("info", "badshop_work/b.png")  # read-only: not recorded
    out = pair.new("recipe").stdout
    assert "2 step(s) from 3 logged command(s)" in out
    recipe = json.loads((pair.new_dir / "badshop_work/recipe.json").read_text())
    assert recipe["steps"][0][2] == "second try"

    recipe["steps"][0][2] = "{caption}"
    (pair.new_dir / "badshop_work/recipe.json").write_text(json.dumps(recipe))
    out = pair.new("run", "badshop_work/recipe.json", "--set", "caption=PROBLEM, LIBURALS??").stdout
    assert "== step 1/2: text lincoln.png 'PROBLEM, LIBURALS??'" in out
    assert "== step 2/2: eyes" in out


def test_run_from_skips_earlier_steps(pair):
    pair.new("recipe", "--clear")
    pair.new("text", "lincoln.png", "x", "-o", "badshop_work/a.png")
    pair.new("eyes", "badshop_work/a.png", "--at", "10", "10", "-o", "badshop_work/b.png")
    pair.new("recipe")
    out = pair.new("run", "badshop_work/recipe.json", "--from", "2").stdout
    assert "step 1/2" not in out and "step 2/2" in out


def test_run_stops_on_failure(pair):
    (pair.new_dir / "bad.json").write_text(json.dumps({"vars": {}, "steps": [["info", "nope.png"], ["info", "lincoln.png"]]}))
    p = pair.new("run", "bad.json", check=False)
    assert p.returncode == 1 and "step 1 failed" in p.stderr and "step 2/2" not in p.stdout


def test_export_copies_without_overwriting(pair):
    pair.new("export", "lincoln.png", "--name", "keep")
    pair.new("export", "lincoln.png", "--name", "keep")
    assert (pair.new_dir / "final/keep.png").exists() and (pair.new_dir / "final/keep_2.png").exists()


# --- in-process replays: run validates the whole recipe before any step runs ---

@pytest.fixture
def here(tmp_path, monkeypatch):
    """A working folder (a level below tmp_path, so `..` stays inside it) holding lincoln.png."""
    work = tmp_path / "work"
    work.mkdir()
    shutil.copy(FIXTURES / "lincoln.png", work / "lincoln.png")
    monkeypatch.chdir(work)
    monkeypatch.setenv("BADSHOP_OUT", str(work / "final"))
    return work


def _run(here, steps, *extra) -> int:
    (here / "r.json").write_text(json.dumps({"vars": {"out": "../escaped.png"}, "steps": steps}))
    return cli.main(["run", "r.json", *extra])


FIRST = ["draw", "lincoln.png", "--circle", "10", "10", "5", "-o", "first.png"]


@pytest.mark.parametrize("step", [["run", "r.json"], ["recipe", "--clear"], ["rm", "-rf", "x"], ["--version"], ["-h"]])
def test_run_refuses_steps_that_are_not_tools(here, capsys, step):
    assert _run(here, [FIRST, step]) == 1
    out, err = capsys.readouterr()
    assert "recipe step 2" in err and "isn't a badshop tool" in err and "Traceback" not in err
    assert "== step" not in out and not (here / "first.png").exists()  # nothing ran


def test_a_recipe_that_runs_itself_is_refused(here, capsys):
    assert _run(here, [["run", "r.json"]]) == 1
    assert "isn't a badshop tool" in capsys.readouterr().err


OUTSIDE = [["-o", "../escaped.png"], ["--out", "{out}"], ["--out=../escaped.png"], ["-o../escaped.png"],
           ["--ou", "../escaped.png"], ["-o", "sub/../../escaped.png"]]


@pytest.mark.parametrize("out", OUTSIDE, ids=lambda o: " ".join(o))
def test_run_refuses_writes_outside_the_folder(here, capsys, out):
    step = ["draw", "lincoln.png", "--circle", "10", "10", "5", *out]
    assert _run(here, [FIRST, step]) == 1
    err = capsys.readouterr().err
    assert "recipe step 2 writes outside this folder: ../escaped.png" in err.replace("sub/../", "")
    assert "--allow-outside" in err
    assert not (here / "first.png").exists() and not (here.parent / "escaped.png").exists()


def test_run_refuses_absolute_outputs(here, capsys):
    target = here.parent / "abs.png"
    assert _run(here, [["draw", "lincoln.png", "--circle", "10", "10", "5", "-o", str(target)]]) == 1
    assert f"writes outside this folder: {target}" in capsys.readouterr().err and not target.exists()


def test_allow_outside_restores_the_old_replay(here):
    step = ["draw", "lincoln.png", "--circle", "10", "10", "5", "-o", "{out}"]
    assert _run(here, [FIRST, step], "--allow-outside") == 0
    assert (here / "first.png").exists() and (here.parent / "escaped.png").exists()


def test_relative_outputs_inside_the_folder_replay(here):
    assert _run(here, [["draw", "lincoln.png", "--circle", "10", "10", "5", "-o", "sub/dir/x.png"]]) == 0
    assert (here / "sub/dir/x.png").exists()


def test_a_step_argparse_rejects_still_fails_at_its_turn(here, capsys):
    # ruling 13.2: the replay runs up to the broken step, which exits 2 with "step N failed"
    assert _run(here, [FIRST, ["eyes", "lincoln.png", "--at", "1"]]) == 2
    assert (here / "first.png").exists() and "step 2 failed" in capsys.readouterr().err


@pytest.mark.parametrize("data", [{"step": []}, [], {"steps": ["info x"]}, {"vars": [1], "steps": []},
                                  {"steps": [[]]}, {"steps": [["info", None]]}, {"steps": "info x"},
                                  {"vars": {"a": [1]}, "steps": []}, "just text"], ids=repr)
def test_run_rejects_malformed_recipes(here, capsys, data):
    (here / "bad.json").write_text(json.dumps(data))
    assert cli.main(["run", "bad.json"]) == 1
    err = capsys.readouterr().err
    assert "bad.json isn't a recipe" in err and "Traceback" not in err


@pytest.mark.parametrize("line", ['{"argv": ["text", "a.png", "hi"', '[1, 2]', '{"argv": "info x"}', '{"argv": []}',
                                  '{"time": "now"}', '{"argv": ["text", 3]}'])
def test_recipe_reports_damaged_history(here, capsys, line):
    history = here / "badshop_work" / "history.jsonl"
    history.parent.mkdir()
    history.write_text(json.dumps({"argv": ["text", "lincoln.png", "hi"], "time": "t"}) + "\n" + line + "\n")
    assert cli.main(["recipe"]) == 1
    err = capsys.readouterr().err
    assert "history.jsonl line 2 is damaged" in err and "recipe --clear" in err and "Traceback" not in err
