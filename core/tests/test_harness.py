import pytest
from PIL import Image

from conftest import FIXTURES, assert_same_image


def test_fixtures_exist_and_are_small():
    for name in ("lincoln.png", "trump.png"):
        with Image.open(FIXTURES / name) as im:
            assert max(im.size) <= 600
    with Image.open(FIXTURES / "emoji_joy.png") as im:
        assert im.mode == "RGBA"


def test_reference_runs(pair):
    out = pair.ref("info", "lincoln.png").stdout
    with Image.open(FIXTURES / "lincoln.png") as im:
        w, h = im.size
    assert out.strip() == f"lincoln.png: {w}x{h}"


def test_assert_same_image_detects_difference(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (4, 4), "red").save(a)
    Image.new("RGB", (4, 4), "red").save(b)
    assert_same_image(a, b)
    Image.new("RGB", (4, 4), "blue").save(b)
    try:
        assert_same_image(a, b)
    except AssertionError:
        return
    raise AssertionError("difference not detected")


def test_assert_same_image_detects_duration_difference(tmp_path):
    frames = [Image.new("P", (4, 4), i) for i in (0, 1)]

    def gif(path, duration):
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, loop=0)

    a, b = tmp_path / "a.gif", tmp_path / "b.gif"
    gif(a, 80)
    gif(b, 80)
    assert_same_image(a, b)
    gif(b, 50)
    with pytest.raises(AssertionError, match="durations"):
        assert_same_image(a, b)
