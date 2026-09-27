import pytest
from PIL import Image

CASES = [
    ["problem, liburals??"],
    ["hand drawn", "--style", "paint", "--at", "300", "400", "--rotate", "10", "--color", "blue"],
    ["Four score and\\nseven covfefes", "--style", "wordart", "--bottom"],
    ["hand\\ndrawn", "--style", "paint", "--size", "30"],
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


def test_text_missing_absolute_font_falls_back_to_built_in(pair):
    missing = pair.new_dir / "no-such-dir" / "Impact.ttf"
    p = pair.new("text", "lincoln.png", "hi", "--font", str(missing), check=False)
    assert p.returncode == 0, p.stderr
    assert "font built-in" in p.stdout
    assert "Traceback" not in p.stderr


def test_text_non_font_file_is_a_clean_error(pair):
    (pair.new_dir / "notes.txt").write_text("not a font at all\n")
    p = pair.new("text", "lincoln.png", "hi", "--font", str(pair.new_dir / "notes.txt"), check=False)
    assert p.returncode == 1
    assert "notes.txt isn't a font file Pillow can read" in p.stderr
    assert "hint: use a .ttf or .otf font file" in p.stderr
    assert "Traceback" not in p.stderr


@pytest.mark.parametrize("side", [12, 5])
def test_text_too_small_image_is_a_clean_error(pair, side):
    Image.new("RGB", (side, side), "white").save(pair.new_dir / "tiny.png")
    p = pair.new("text", "tiny.png", "a b c d e f g h", check=False)
    assert p.returncode == 1
    assert "the image is too small for this caption" in p.stderr
    assert "hint: give size, or caption a bigger image" in p.stderr
    assert "Traceback" not in p.stderr


def test_font_lookup_retries_a_download_that_failed(tmp_path, monkeypatch):
    from badshop.engine import assets, text
    from badshop.engine.errors import EngineError

    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])
    monkeypatch.setitem(text.FONT_CANDIDATES, "impact", ["BadshopTestDownload.ttf", "BadshopTestFallback.ttf"])
    monkeypatch.setitem(text.FONT_DOWNLOADS, "BadshopTestDownload.ttf", assets.Pinned("https://e.org/f.ttf", "0" * 64, 1))
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "BadshopTestFallback.ttf").write_bytes(b"")
    downloads = []

    def cached(name, url, progress=None, sha256=None, size=None):
        downloads.append(name)
        if len(downloads) == 1:
            raise EngineError(f"couldn't download {name} (offline)")
        (tmp_path / name).write_bytes(b"")
        return tmp_path / name
    monkeypatch.setattr(assets, "cached", cached)
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestFallback.ttf")  # offline
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestDownload.ttf")  # back online
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestDownload.ttf")
    assert len(downloads) == 2  # a definitive answer is remembered


@pytest.mark.parametrize("style", ["impact", "paint", "wordart"])
@pytest.mark.parametrize("brk", ["\\n", "\n", "\r\n"], ids=["typed", "newline", "crlf"])
def test_line_breaks_in_every_style(monkeypatch, style, brk):
    # A typed \n (the CLI) and a real newline (JSON from a model, a UI textarea) both break the line;
    # Impact used to upper-case the typed one into a literal "\N".
    from badshop.engine import text
    from badshop.tools.runner import run_tool
    from conftest import FIXTURES
    from memstore import MemoryStore

    seen = []
    render = text.render_text
    monkeypatch.setattr(text, "render_text", lambda lines, *a: seen.append(lines) or render(lines, *a))
    store = MemoryStore()
    ref = store.add(Image.open(FIXTURES / "lincoln.png").convert("RGB"), "lincoln.png")
    run = run_tool("text", {"image": ref, "text": f"top line{brk}bottom line", "style": style, "size": 30}, store)
    words = ["top line", "bottom line"]
    assert seen == [[w.upper() for w in words] if style == "impact" else words]
    assert run.result.lines[0].startswith("text: 2 line(s)")
