import pytest
from PIL import Image, ImageStat

from badshop.engine.errors import EngineError
from badshop.engine.finish import deepfry
from badshop.tools.runner import run_tool
from conftest import FIXTURES
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


def test_deepfry_level_increases_saturation():
    im = Image.open(FIXTURES / "trump.png").convert("RGB")
    low, _ = deepfry(im, 1)
    high, _ = deepfry(im, 5)
    sat = lambda x: ImageStat.Stat(x.convert("HSV")).mean[1]  # noqa: E731
    assert sat(high) > sat(low)


def test_animate_fry_runs(pair):
    out = pair.new("animate", "lincoln.png", "--effect", "zoom", "--fry", "5", "--name", "z").stdout
    assert "fried to level 5" in out and Image.open(pair.new_dir / "final/z.gif").n_frames > 1


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
