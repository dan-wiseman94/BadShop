from PIL import Image

from conftest import FIXTURES, assert_same_image


def test_fixtures_exist_and_are_small():
    for name in ("lincoln.png", "trump.png"):
        im = Image.open(FIXTURES / name)
        assert max(im.size) <= 600
    assert Image.open(FIXTURES / "emoji_joy.png").mode == "RGBA"


def test_reference_runs(pair):
    out = pair.ref("info", "lincoln.png").stdout
    w, h = Image.open(FIXTURES / "lincoln.png").size
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
