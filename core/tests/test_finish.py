import importlib.util

import numpy as np
import pytest
from PIL import Image, ImageStat

from badshop.engine.errors import EngineError
from badshop.engine.finish import deepfry
from badshop.tools.runner import run_tool
from conftest import FIXTURES, REFERENCE
from memstore import MemoryStore

SAVES = [
    ["--quality", "20", "--passes", "3", "--name", "s"],
    ["--lowres", "0.3", "--name", "s"],
    ["--gif", "--colors", "32", "--name", "s"],
]


@pytest.mark.parametrize("args", SAVES)
def test_save_parity(pair, args):
    assert pair.new("save", "lincoln.png", *args).stdout.replace(str(pair.new_dir), "") == \
        pair.ref("save", "lincoln.png", *args).stdout.replace(str(pair.ref_dir), "")
    ext = ".gif" if "--gif" in args else ".jpg"
    pair.assert_same(f"final/s{ext}")


ANIMS = [
    ["--effect", "none"],
    ["--effect", "shake", "--frames", "6", "--seed", "2"],
    ["--effect", "flash"],
    ["--effect", "zoom", "--at", "300", "250", "--amount", "2.5", "--hold", "2"],
    ["--effect", "spin", "--frames", "5", "--delay", "50"],
]


@pytest.mark.parametrize("args", ANIMS, ids=lambda a: a[1])
def test_animate_parity(pair, args):
    for side in (pair.ref, pair.new):
        side("animate", "lincoln.png", "trump.png", *args, "--name", "a")
    pair.assert_same("final/a.gif")


def test_animate_out_suffix_parity(pair):
    for side in (pair.ref, pair.new):
        side("animate", "lincoln.png", "trump.png", "--effect", "flash", "-o", "anim.png")
    pair.assert_same("anim.png")


def test_final_names_never_overwrite(pair):
    pair.new("deepfry", "lincoln.png", "--name", "meme")
    pair.new("deepfry", "lincoln.png", "--name", "meme")
    assert (pair.new_dir / "final/meme.jpg").exists() and (pair.new_dir / "final/meme_2.jpg").exists()


def test_deepfry_is_deterministic_per_seed():
    im = Image.open(FIXTURES / "lincoln.png").convert("RGB")
    a, qa = deepfry(im, 4, seed=7)
    b, _ = deepfry(im, 4, seed=7)
    c, _ = deepfry(im, 4, seed=8)
    assert a.tobytes() == b.tobytes() and a.tobytes() != c.tobytes()
    assert qa == round(22 + (4 - 22) * 0.75)


def test_negative_seed_is_deterministic():
    # numpy rejects negative seeds; deepfry folds any int into its range instead of crashing.
    im = Image.open(FIXTURES / "lincoln.png").convert("RGB")
    a, _ = deepfry(im, 3, seed=-1)
    b, _ = deepfry(im, 3, seed=-1)
    assert a.tobytes() == b.tobytes()


def test_animate_fry_accepts_a_negative_seed():
    # The reference accepts `animate --fry 2 --seed -1` (random.Random(-1), unseeded fry).
    store = MemoryStore()
    ref = store.add(Image.open(FIXTURES / "lincoln.png").convert("RGB"), "lincoln.png")
    run = run_tool("animate", {"images": [ref], "frames": 2, "fry": 2, "seed": -1}, store)
    assert len(run.result.outputs[0].frames) == 2


@pytest.fixture(scope="module")
def reference():
    spec = importlib.util.spec_from_file_location("reference_badshop", REFERENCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("tint", [True, False], ids=["tint", "no_tint"])
@pytest.mark.parametrize("level", [1, 3, 5])
def test_deepfry_matches_reference_outside_the_grain(reference, monkeypatch, level, tint):
    # The grain is the one intended change, so hand the reference the port's seed-1 grain:
    # everything else in deepfry must then be byte-identical.
    def seeded_noise(size, sigma):
        w, h = size
        grain = np.random.default_rng(1).normal(128.0, sigma, size=(h, w)).clip(0, 255).astype(np.uint8)
        return Image.fromarray(grain, "L")

    monkeypatch.setattr(reference.Image, "effect_noise", seeded_noise)
    im = Image.open(FIXTURES / "lincoln.png").convert("RGB")
    ref_im, ref_quality = reference.deepfry(im, level, tint=tint)
    new_im, new_quality = deepfry(im, level, tint=tint, seed=1)
    assert new_quality == ref_quality
    assert (new_im.mode, new_im.size) == (ref_im.mode, ref_im.size)
    assert new_im.tobytes() == ref_im.tobytes()


def test_deepfry_stdout_parity(pair):
    args = ["--level", "5", "--no-tint", "--name", "d"]
    assert pair.new("deepfry", "lincoln.png", *args).stdout.replace(str(pair.new_dir), "") == \
        pair.ref("deepfry", "lincoln.png", *args).stdout.replace(str(pair.ref_dir), "")


def test_deepfry_level_increases_saturation():
    im = Image.open(FIXTURES / "trump.png").convert("RGB")
    low, _ = deepfry(im, 1)
    high, _ = deepfry(im, 5)
    sat = lambda x: ImageStat.Stat(x.convert("HSV")).mean[1]  # noqa: E731
    assert sat(high) > sat(low)


def test_animate_fry_runs(pair):
    out = pair.new("animate", "lincoln.png", "--effect", "zoom", "--fry", "5", "--name", "z").stdout
    assert "fried to level 5" in out
    with Image.open(pair.new_dir / "final/z.gif") as im:
        assert im.n_frames > 1


def test_animate_fry_keeps_every_frame(pair):
    # Each frame fries with seed + k: one shared seed would make identical frames the GIF writer merges.
    pair.new("animate", "lincoln.png", "--frames", "4", "--fry", "2", "--name", "f")
    with Image.open(pair.new_dir / "final/f.gif") as im:
        assert im.n_frames == 4


def test_zoom_out_is_a_clean_error():
    # The reference crashes with "box offset can't be negative" when the zoom factor is below 1.
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (40, 40)), "x.png")
    with pytest.raises(EngineError, match="zoom"):
        run_tool("animate", {"images": [ref], "effect": "zoom", "amount": 0.5}, store)
