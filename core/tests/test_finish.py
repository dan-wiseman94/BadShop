import numpy as np
import pytest
from PIL import Image, ImageStat

from badshop.engine.errors import EngineError
from badshop.engine.finish import deepfry
from badshop.tools.runner import run_tool
from conftest import FIXTURES, assert_same_image
from memstore import MemoryStore

SAVES = [
    ["--quality", "20", "--passes", "3", "--name", "s"],
    ["--lowres", "0.3", "--name", "s"],
    ["--gif", "--colors", "32", "--name", "s"],
]


@pytest.mark.parametrize("args", SAVES)
def test_save_parity(pair, args):
    ext = ".gif" if "--gif" in args else ".jpg"
    pair.check("save", "lincoln.png", *args, files=[f"final/s{ext}"])


ANIMS = [
    ["--effect", "none"],
    ["--effect", "shake", "--frames", "6", "--seed", "2"],
    ["--effect", "flash"],
    ["--effect", "zoom", "--at", "300", "250", "--amount", "2.5", "--hold", "2"],
    ["--effect", "spin", "--frames", "5", "--delay", "50"],
]


@pytest.mark.parametrize("args", ANIMS, ids=lambda a: a[1])
def test_animate_parity(pair, args):
    out = pair.check("animate", "lincoln.png", "trump.png", *args, "--name", "a", files=["final/a.gif"])
    assert out.startswith("animated: <CWD>/final/a.gif\n")


def test_animate_out_suffix_parity(pair):
    pair.check("animate", "lincoln.png", "trump.png", "--effect", "flash", "-o", "anim.png", files=["anim.png"])


# Finished files without --name are named after the input, minus a _work or _result suffix.
DEFAULT_NAMES = [
    (["save", "{}"], "{}.jpg"),
    (["save", "{}", "--gif"], "{}.gif"),
    (["animate", "{}", "trump.png", "--effect", "flash"], "{}_flash.gif"),
    (["deepfry", "{}", "--level", "2"], "{}_deepfried.jpg"),
]


@pytest.mark.parametrize("image", ["lincoln.png", "badshop_work/lincoln_work.png"])
@pytest.mark.parametrize("args, name", DEFAULT_NAMES, ids=lambda v: v[0] if isinstance(v, list) else None)
def test_default_finished_names_parity(pair, image, args, name):
    if image.startswith("badshop_work/"):
        pair.check("prep", "lincoln.png", files=["badshop_work/lincoln_work.png"])
    final = "final/" + name.format("lincoln")
    fried = args[0] == "deepfry"  # its grain is the intended difference: same name and stdout, other pixels
    out = pair.check(*[a.format(image) for a in args], files=[] if fried else [final])
    assert out.split("\n")[0].endswith(f": <CWD>/{final}")
    assert (pair.ref_dir / final).is_file() and (pair.new_dir / final).is_file()


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
    pair.check("deepfry", "lincoln.png", "--level", "5", "--no-tint", "--name", "d")


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


def _keyed_inputs(folder):
    """Transparent inputs whose RGB copy (to_rgb) keeps a colour key the GIF writer can't take, as
    written by the e2e review: a palette GIF with a transparent index, and RGB / L PNGs with a tRNS key.
    Each has an `_opaque` twin with the same pixels and no key."""
    joy = Image.open(FIXTURES / "emoji_joy.png").convert("RGBA")
    joy.save(folder / "sticker.gif")
    with Image.open(folder / "sticker.gif") as im:
        assert "transparency" in im.info
        im.convert("RGB").save(folder / "sticker_opaque.png")
    rgb = Image.new("RGB", (60, 40), (0, 255, 0))
    rgb.paste((255, 0, 0), (10, 10, 30, 30))
    rgb.save(folder / "keyed.png", transparency=(0, 255, 0))
    rgb.save(folder / "keyed_opaque.png")
    grey = Image.new("L", (60, 40), 7)
    grey.paste(200, (10, 10, 30, 30))
    grey.save(folder / "keyed_l.png", transparency=7)
    grey.save(folder / "keyed_l_opaque.png")


KEYED = {"sticker.gif": "sticker_opaque.png", "keyed.png": "keyed_opaque.png", "keyed_l.png": "keyed_l_opaque.png"}
GIF_STEPS = [
    ["save", "{}", "--gif", "--name", "out"],
    ["save", "{}", "--gif", "-o", "out.png"],
    ["animate", "{}", "--effect", "shake", "--frames", "2", "--name", "out"],
    ["animate", "{}", "lincoln.png", "--name", "out"],
    ["animate", "lincoln.png", "{}", "--effect", "flash", "--name", "out"],
]


@pytest.mark.parametrize("step", GIF_STEPS, ids=["save-gif", "save-gif-o-png", "shake", "first-of-two", "second-of-two"])
@pytest.mark.parametrize("image", KEYED)
def test_gifs_of_colour_keyed_images(pair, image, step):
    # The reference crashes on all of these (the key survives convert("RGB") as a tuple). Like its JPEG,
    # the GIF shows the RGB picture: exactly the pixels of the same image without the key.
    _keyed_inputs(pair.new_dir)
    opaque = KEYED[image]
    out = "out.png" if "-o" in step else "final/out.gif"
    p = pair.new(*[a.format(image) for a in step], check=False)
    assert p.returncode == 0 and "Traceback" not in p.stderr, p.stderr
    (pair.new_dir / out).rename(pair.new_dir / "keyed_result")
    pair.new(*[a.format(opaque) for a in step])
    assert_same_image(pair.new_dir / "keyed_result", pair.new_dir / out)


@pytest.mark.parametrize("image", KEYED)
def test_work_files_of_colour_keyed_images_keep_the_reference_key(pair, image):
    # Only the GIF writers drop the key: a caption's PNG keeps it, byte for byte like the reference.
    _keyed_inputs(pair.ref_dir)
    _keyed_inputs(pair.new_dir)
    for side in (pair.ref, pair.new):
        side("text", image, "hi", "--size", "12")
    pair.assert_same("badshop_work/result.png")
