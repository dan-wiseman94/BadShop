import json


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
