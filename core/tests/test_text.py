import pytest

CASES = [
    ["problem, liburals??"],
    ["hand drawn", "--style", "paint", "--at", "300", "400", "--rotate", "10", "--color", "blue"],
    ["Four score and\\nseven covfefes", "--style", "wordart", "--bottom"],
    ["tiny", "--size", "18", "--margin", "4"],
]


@pytest.mark.parametrize("args", CASES)
def test_text_parity(pair, args):
    ref = pair.ref("text", "lincoln.png", *args).stdout
    new = pair.new("text", "lincoln.png", *args).stdout
    assert new == ref
    pair.assert_same("badshop_work/result.png")


def test_text_unicode_parity(pair):
    args = ["text", "trump.png", "PROBLEM, LIBURALS?? 😂 ünïcödé", "-o", "u.png"]
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("u.png")


def test_text_bad_color_is_a_clean_error(pair):
    p = pair.new("text", "lincoln.png", "hi", "--style", "paint", "--color", "notacolor", check=False)
    assert p.returncode == 1
    assert "unknown color 'notacolor'" in p.stderr and "hint:" in p.stderr
    assert "Traceback" not in p.stderr


def test_text_nothing_to_write_is_a_clean_error(pair):
    p = pair.new("text", "lincoln.png", "   ", check=False)
    assert p.returncode == 1
    assert "nothing to write" in p.stderr and "hint: give some words" in p.stderr
    assert "Traceback" not in p.stderr


def test_font_lookup_follows_data_dir(tmp_path, monkeypatch):
    from badshop.engine.text import find_font_file

    name = "badshop-test-font.ttf"
    for d in ("a", "b"):
        (tmp_path / d / "fonts").mkdir(parents=True)
        (tmp_path / d / "fonts" / name).write_bytes(b"")
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "a"))
    assert find_font_file("impact", name) == str(tmp_path / "a" / "fonts" / name)
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "b"))
    assert find_font_file("impact", name) == str(tmp_path / "b" / "fonts" / name)
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "empty"))
    assert find_font_file("impact", name) is None
