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
    # Pillow also searches by basename on macOS, where Impact is a system font.
    missing = pair.new_dir / "no-such-dir" / "BadshopMissingTestFont.ttf"
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
    monkeypatch.setattr(text, "DOWNLOAD_RETRY_S", 0.0)  # no retry window: the next lookup tries again
    monkeypatch.setattr(text, "_download_failed_at", {})
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
    monkeypatch.setattr(text, "render_text",
                        lambda lines, *a, **kw: seen.append(lines) or render(lines, *a, **kw))
    store = MemoryStore()
    ref = store.add(Image.open(FIXTURES / "lincoln.png").convert("RGB"), "lincoln.png")
    run = run_tool("text", {"image": ref, "text": f"top line{brk}bottom line", "style": style, "size": 30}, store)
    words = ["top line", "bottom line"]
    assert seen == [[w.upper() for w in words] if style == "impact" else words]
    assert run.result.lines[0].startswith("text: 2 line(s)")


def test_exact_text_box_preserves_case_spaces_blank_lines_and_alignment(monkeypatch):
    from PIL import ImageFont
    from badshop.engine import text
    monkeypatch.setattr(text, "load_font", lambda style, size, explicit: (ImageFont.load_default(size=size), "fixture"))
    params = text.TextParams(image="source", text="Hello  World\n\nNext", preserve_case=True,
        preserve_line_breaks=True, box=(20, 20, 280, 180), align="right", size=18, margin=5, overflow="error")
    source = Image.new("RGB", (300, 200), "gray")
    result = text.caption(params, source).outputs[0].image
    layer = text.render_text(["Hello  World", "", "Next"], ImageFont.load_default(size=18),
        "impact", "red", align="right")
    expected = source.copy()
    expected.paste(layer, (280 - 5 - layer.width, 25), layer)
    assert result.tobytes() == expected.tobytes()
    assert source.getextrema() == ((128, 128),) * 3


def test_text_box_overflow_errors_or_shrinks_without_clipping(monkeypatch):
    from PIL import ImageFont
    from badshop.engine import text
    from badshop.engine.errors import EngineError
    monkeypatch.setattr(text, "load_font", lambda style, size, explicit: (ImageFont.load_default(size=size), "fixture"))
    source = Image.new("RGB", (200, 160), "gray")
    params = text.TextParams(image="source", text="Exact words", preserve_line_breaks=True,
        box=(20, 20, 180, 140), margin=5, size=100, overflow="error")
    with pytest.raises(EngineError, match="clip words"):
        text.caption(params, source)
    output = text.caption(params.model_copy(update={"overflow": "shrink"}), source).outputs[0].image
    from PIL import ImageChops
    bounds = ImageChops.difference(output, source).getbbox()
    assert bounds is not None
    assert 20 <= bounds[0] < bounds[2] <= 180
    assert 20 <= bounds[1] < bounds[3] <= 140
    with pytest.raises(EngineError, match="text box"):
        text.caption(params.model_copy(update={"box": (20, 20, 201, 140)}), source)


def test_bundled_bubble_is_portable_hard_edged_and_preserves_source(monkeypatch):
    from badshop.engine import text
    from badshop.tools.fonts import font_names
    def no_lookup(*args):
        raise AssertionError("portable captions must not look up or download fonts")
    monkeypatch.setattr(text, "find_font_file", no_lookup)
    params = text.TextParams(image="source", text="Hello\nWorld", font="bundled", style="paint",
        preserve_case=True, preserve_line_breaks=True, size=18, fit_exact=True, margin=5,
        frame="bubble", frame_color="yellow", frame_padding=6, tail=(130, 135), at=(100, 65))
    source = Image.new("RGB", (200, 160), "navy")
    result = text.caption(params, source)
    assert "bundled" in font_names()
    assert set(result.outputs[0].image.get_flattened_data()) <= {(0, 0, 128), (255, 255, 0), (255, 0, 0), (0, 0, 0)}
    assert result.outputs[0].image.getpixel((130, 135)) != (0, 0, 128)
    assert result.data["element_bounds"][3] >= 136
    assert source.getextrema() == ((0, 0), (0, 0), (128, 128))
    assert text.caption(params, source).outputs[0].encode() == result.outputs[0].encode()


def test_bundled_font_and_frame_errors_are_explicit():
    from badshop.engine import text
    from badshop.engine.errors import EngineError
    source = Image.new("RGB", (200, 100), "white")
    with pytest.raises(EngineError, match="Latin-1"):
        text.caption(text.TextParams(image="source", text="你好", font="bundled"), source)
    with pytest.raises(EngineError, match="no room"):
        text.caption(text.TextParams(image="source", text="Hi", font="bundled", frame="box", frame_padding=100), source)
    with pytest.raises(EngineError, match="tail"):
        text.caption(text.TextParams(image="source", text="Hi", font="bundled", frame="bubble", tail=(250, 0)), source)


@pytest.mark.parametrize("style", ["impact", "paint", "wordart"])
def test_framed_caption_lettering_has_binary_alpha(style):
    from badshop.engine.text import render_text
    from badshop.engine.common import font
    layer = render_text(["Hard edges"], font(18), style, "red", hard_edges=True)
    assert set(layer.getchannel("A").get_flattened_data()) <= {0, 255}
