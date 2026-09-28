import builtins
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import typing
from pathlib import Path

import pytest
from PIL import EpsImagePlugin, Image, UnidentifiedImageError
from pydantic import ValidationError

from badshop import files
from badshop.cli import filestore
from badshop.cli import main as cli_main
from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.session import artifacts
from badshop.session.artifacts import (IMPORT_FORMATS, MIME, REF_HINT, WORKING_MAX, ArtifactStore, describe,
                                       short)
from badshop.session.models import (EXT, SCHEMA, ArtifactMeta, ImageFormat, Message, Part, SessionData,
                                    Source, Step, StepError)

EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"


def encode(im: Image.Image, fmt: str = "PNG", **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def gif3() -> bytes:
    frames = [Image.new("RGB", (30, 20), c) for c in ("red", "lime", "blue")]
    return encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)


# --- files.py: the output folder rule and never-overwrite names, shared by the CLI and sessions ---

def test_final_path_lives_in_files_and_the_cli_still_exports_it(tmp_path):
    assert filestore.final_path is files.final_path
    first = files.final_path(tmp_path / "out", "lincoln", ".png")
    assert first == tmp_path / "out" / "lincoln.png"
    first.write_bytes(b"x")
    assert files.final_path(tmp_path / "out", "lincoln", ".png") == tmp_path / "out" / "lincoln_2.png"
    with pytest.raises(EngineError, match="bad file name"):
        files.final_path(tmp_path / "out", "../x", ".png")


def test_default_output_dir_is_the_cli_rule(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "mine"))
    assert files.default_output_dir() == tmp_path / "mine"
    assert cli_main.final_dir() == tmp_path / "mine"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("BADSHOP_OUT", "")  # set but empty: the default, as before
    assert files.default_output_dir() == tmp_path / "home" / "Pictures" / "badshop"
    monkeypatch.delenv("BADSHOP_OUT")
    assert files.default_output_dir() == tmp_path / "home" / "Pictures" / "badshop"
    assert cli_main.final_dir() == tmp_path / "home" / "Pictures" / "badshop"


# --- models.py ---

def test_session_data_saves_schema_under_its_alias_and_round_trips():
    aid = "a" * 64
    meta = ArtifactMeta(id=aid, label="lincoln_work", width=457, height=600, format="PNG", mime="image/png",
                        source=Source(kind="openverse", url="https://x.test/y.jpg", license="CC BY 2.0"))
    step = Step(id="s1", index=1, tool="cutout", params={"image": aid, "box": [1, 2, 30, 40]},
                actor="agent:fake", status="error", error=StepError(message="box is empty", hint="use find"))
    msg = Message(id="m1", role="user",
                  content=[Part(type="text", text="hi"), Part(type="image", artifact_id=aid)])
    data = SessionData(id="x1", name="Untitled", created_at=1.5, messages=[msg], steps=[step],
                       artifacts={aid: meta}, transcript=[{"role": "user", "content": "hi"}])
    dumped = data.model_dump(mode="json", by_alias=True)
    assert dumped["schema"] == SCHEMA == 1 and "schema_" not in dumped
    assert dumped["approval_mode"] == "ask_changes" and dumped["provider_profile_id"] is None
    assert dumped["steps"][0]["outputs"] == [] and dumped["steps"][0]["edited"] is False
    back = SessionData.model_validate_json(json.dumps(dumped))
    assert back == data and back.artifacts[aid].ext == ".png"
    assert SessionData.model_validate({**dumped, "schema": 7}).schema_ == 7  # by alias (session.json)
    assert SessionData(schema_=2, id="x", name="n", created_at=0).schema_ == 2  # and by name


def test_models_import_without_warnings():
    # a field called `schema` would shadow BaseModel.schema (a UserWarning); -W error fails on any warning
    p = subprocess.run([sys.executable, "-W", "error", "-c", "import badshop.session.artifacts"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr


def test_artifact_meta_is_frozen_and_validated():
    meta = ArtifactMeta(id="b" * 64, label="x", width=1, height=1, format="GIF", mime="image/gif")
    with pytest.raises(ValidationError):
        meta.produced_by = "s9"
    for bad_id in ("../../etc/passwd", "B" * 64, "b" * 63):
        with pytest.raises(ValidationError):
            ArtifactMeta(id=bad_id, label="x", width=1, height=1, format="PNG", mime="image/png")
    with pytest.raises(ValidationError):
        ArtifactMeta(id="b" * 64, label="x", width=1, height=1, format="EPS", mime="application/postscript")
    with pytest.raises(ValidationError):
        Step(id="s1", index=1, tool="info", params={}, actor="user", status="finished")


def test_every_import_format_has_an_extension_and_a_mime_type():
    assert set(typing.get_args(ImageFormat)) == set(IMPORT_FORMATS) == set(MIME) == set(EXT)
    assert {f: EXT[f] for f in IMPORT_FORMATS} == {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif",
                                                    "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff"}


# --- ArtifactStore.add / data / image / drop ---

def test_add_stores_bytes_under_their_sha256():
    store = ArtifactStore()
    data = encode(Image.new("RGB", (30, 20), "red"))
    meta = store.add(data, "red", produced_by="s1")
    assert meta.id == hashlib.sha256(data).hexdigest()
    assert (meta.label, meta.width, meta.height, meta.format, meta.mime, meta.frames, meta.ext) == \
        ("red", 30, 20, "PNG", "image/png", 1, ".png")
    assert (meta.produced_by, meta.source, meta.original_id) == ("s1", None, None)
    assert meta.id in store and "red" not in store and store.ids() == [meta.id]
    assert store.meta[meta.id] is meta
    assert store.data(meta.id) == data
    with store.image(meta.id) as im:
        assert im.size == (30, 20) and im.getpixel((0, 0)) == (255, 0, 0)
    assert short(meta.id) == meta.id[:8] and describe(meta) == f"{meta.id[:8]} (red, 30x20)"


def test_the_same_bytes_keep_their_first_meta():
    # store half of Review Focus 2: an output produced again (or re-imported) keeps its first produced_by
    store = ArtifactStore()
    data = encode(Image.new("RGBA", (10, 10), (0, 0, 255, 128)))
    first = store.add(data, "lincoln_cutout", produced_by="s2")
    again = store.add(data, "other", produced_by="s5", source=Source(kind="url", url="https://x.test/a.png"))
    assert again is first and store.ids() == [first.id]
    assert (again.label, again.produced_by, again.source) == ("lincoln_cutout", "s2", None)


@pytest.mark.parametrize("fmt", IMPORT_FORMATS)
def test_add_records_each_format(fmt):
    store = ArtifactStore()
    meta = store.add(encode(Image.new("RGB", (8, 6), "white"), fmt), "x")
    assert (meta.format, meta.mime, meta.ext, meta.width, meta.height) == (fmt, MIME[fmt], EXT[fmt], 8, 6)


def test_add_counts_frames_and_stores_a_phone_mpo_as_jpeg():
    store = ArtifactStore()
    gif = store.add(gif3(), "anim")
    assert (gif.format, gif.frames, gif.ext) == ("GIF", 3, ".gif")
    left, right = Image.new("RGB", (16, 12), "red"), Image.new("RGB", (16, 12), "blue")
    mpo = store.add(encode(left, "MPO", save_all=True, append_images=[right]), "phone")
    assert (mpo.format, mpo.mime, mpo.ext, mpo.frames) == ("JPEG", "image/jpeg", ".jpg", 2)


def test_add_refuses_what_is_not_an_image():
    store = ArtifactStore()
    png = encode(Image.new("RGB", (64, 64), "red"))
    for bad in (b"", b"not an image", EPS, png[: len(png) // 2]):
        with pytest.raises(EngineError, match="isn't an image badshop can open") as e:
            store.add(bad, "x")
        assert e.value.hint and "BytesIO" not in e.value.message
    assert store.ids() == []


def tiff_with_a_broken_page_chain() -> bytes:
    """A 3-page TIFF whose first page is sound but whose link to the second page points one byte into it."""
    pages = [Image.new("RGB", (8, 6), c) for c in ("red", "lime", "blue")]
    data = encode(pages[0], "TIFF", save_all=True, append_images=pages[1:])
    assert data[:4] == b"II*\0"  # little-endian
    first = struct.unpack_from("<I", data, 4)[0]
    link = first + 2 + 12 * struct.unpack_from("<H", data, first)[0]  # the first IFD's next-IFD offset
    return data[:link] + struct.pack("<I", struct.unpack_from("<I", data, link)[0] + 1) + data[link + 4:]


def test_damage_past_the_first_frame_is_refused_cleanly():
    # counting frames reads on past the frame the decode loaded; a hostile project member (Task 9 rebuilds
    # its store with add) or a download cut short there is still an EngineError, never a traceback
    bad = tiff_with_a_broken_page_chain()
    with load_image(bad, formats=IMPORT_FORMATS) as im:
        assert im.size == (8, 6)  # the first page decodes: only the page count meets the damage
    store = ArtifactStore()
    for call in (lambda: store.add(bad, "scan"), lambda: store.import_image(bad, "scan.tiff")):
        with pytest.raises(EngineError, match="isn't an image badshop can open") as e:
            call()
        assert "PNG, JPEG" in e.value.hint
    assert store.ids() == []
    gif = gif3()
    for cut in range(len(gif)):  # every truncation of an animation: stored (its first frame opens) or refused
        for call in (store.add, store.import_image):
            try:
                call(gif[:cut], "dance.gif")
            except EngineError:
                pass
    for id in store.ids():
        store.image(id).close()


def test_unknown_ids_are_clean_errors_and_drop_forgets():
    store = ArtifactStore()
    keep = store.add(encode(Image.new("RGB", (4, 4), "red")), "keep")
    gone = store.add(encode(Image.new("RGB", (4, 4), "blue")), "gone")
    store.drop([gone.id, "0" * 64])  # unknown ids are ignored
    assert store.ids() == [keep.id] and gone.id not in store
    for call in (store.data, store.image):
        with pytest.raises(EngineError, match=f"no such artifact: {gone.id}") as e:
            call(gone.id)
        assert e.value.hint == REF_HINT


def test_the_eps_decoder_is_never_reached(monkeypatch):
    reached = []
    monkeypatch.setattr(EpsImagePlugin.EpsImageFile, "_open", lambda self: reached.append(1))
    with pytest.raises(UnidentifiedImageError):
        Image.open(io.BytesIO(EPS))  # with every decoder on, Pillow hands these bytes to EPS (Ghostscript)
    assert reached == [1]
    store = ArtifactStore()
    for call in (lambda: store.add(EPS, "x"), lambda: store.import_image(EPS, "x.eps")):
        with pytest.raises(EngineError, match="isn't an image badshop can open"):
            call()
    assert reached == [1] and store.ids() == []


# --- ArtifactStore.resolve ---

def test_resolve_takes_full_ids_and_unique_prefixes():
    store = ArtifactStore()
    meta = store.add(encode(Image.new("RGB", (4, 4), "red")), "x")
    for ref in (meta.id, meta.id.upper(), meta.id[:8], meta.id[:6], meta.id[:6].upper(), f" {meta.id[:8]} "):
        assert store.resolve(ref) == meta.id


def test_resolve_refuses_everything_else_without_touching_the_disk(monkeypatch, tmp_path):
    store = ArtifactStore()
    meta = store.add(encode(Image.new("RGB", (4, 4), "red")), "x")
    real = tmp_path / "real.png"
    real.write_bytes(store.data(meta.id))
    refs = [str(real), "real.png", "../../etc/passwd", "https://example.com/x.png", "", meta.id[:5],
            meta.id[:8] + "zz", "0" * 64]

    def no_disk(*a, **k):
        raise AssertionError("resolve touched the filesystem")

    errors = []
    with monkeypatch.context() as m:
        for name in ("open", "stat", "lstat", "listdir", "scandir"):
            m.setattr(os, name, no_disk)
        m.setattr(builtins, "open", no_disk)
        for ref in refs:
            try:
                store.resolve(ref)
            except EngineError as e:
                errors.append((e.message, e.hint))
    assert errors == [(f"no such artifact: {ref}", REF_HINT) for ref in refs]


def test_resolve_refuses_an_ambiguous_prefix():
    store = ArtifactStore()
    for i in "01":
        aid = "abcdef" + i * 58
        store.meta[aid] = ArtifactMeta(id=aid, label=i, width=1, height=1, format="PNG", mime="image/png")
    with pytest.raises(EngineError, match="ambiguous") as e:
        store.resolve("ABCDEF")
    assert "more characters" in e.value.hint
    assert store.resolve("abcdef1") == "abcdef" + "1" * 58


# --- ArtifactStore.import_image ---

def test_import_makes_a_working_copy_and_keeps_the_original_bytes():
    store = ArtifactStore()
    photo = encode(Image.new("RGB", (3000, 1500), "green"), "JPEG", quality=90)
    src = Source(kind="clipboard")
    working, original = store.import_image(photo, "/home/u/Pictures/Holiday Photo.JPG", source=src)
    assert (original.label, original.format, original.mime, original.ext) == \
        ("holiday_photo", "JPEG", "image/jpeg", ".jpg")
    assert (original.width, original.height) == (3000, 1500) and store.data(original.id) == photo
    assert (working.label, working.format, working.width, working.height) == \
        ("holiday_photo_work", "PNG", 1000, 500)
    assert working.original_id == original.id and working.source == original.source == src
    assert working.produced_by is None and original.original_id is None
    assert describe(working) == f"{working.id[:8]} (holiday_photo_work, 1000x500)"
    with store.image(working.id) as im:
        assert im.mode == "RGB" and max(im.size) == WORKING_MAX
    again = store.import_image(photo, "renamed.jpg")  # the same file twice: nothing new
    assert again == (working, original) and store.ids() == [original.id, working.id]
    # a source tool's picture (Task 7): both halves are credited to the step that brought it in
    f_work, f_orig = ArtifactStore().import_image(photo, "holiday.jpg", src, produced_by="s4")
    assert f_work.produced_by == f_orig.produced_by == "s4" and f_work.original_id == f_orig.id
    assert f_work.source == f_orig.source == src
    assert store.import_image(photo, "x.jpg", produced_by="s9") == (working, original)  # stored: first meta wins
    with pytest.raises(TypeError):
        store.import_image(photo, "x.jpg", src, "s9")  # produced_by is keyword-only
    assert store.ids() == [original.id, working.id]


def test_a_badshop_png_is_its_own_working_copy():
    store = ArtifactStore()
    data = encode(Image.new("RGB", (50, 40), "red"))  # small, upright, PNG: what an import would make
    working, original = store.import_image(data, "lincoln_lasers.png")
    assert working is original and store.ids() == [working.id] and store.data(working.id) == data
    assert (working.label, working.original_id) == ("lincoln_lasers_work", None)
    scan, _ = store.import_image(encode(Image.new("RGB", (1200, 900), "red"), "BMP"), "scan.bmp")
    w, o = store.import_image(store.data(scan.id), "scan_work.png")  # an exported working copy, re-imported
    assert w is o is scan and len(store.ids()) == 3
    one, same = ArtifactStore().import_image(data, "emoji_1f602.png", produced_by="s7")  # still one
    assert one is same and (one.label, one.produced_by, one.original_id) == ("emoji_1f602_work", "s7", None)


def test_import_keeps_transparency_where_prep_would_flatten_it():
    store = ArtifactStore()
    sticker = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    sticker.paste((255, 0, 0, 255), (20, 0, 40, 20))
    working, _ = store.import_image(encode(sticker), "sticker.png")
    with store.image(working.id) as im:
        assert im.mode == "RGBA" and im.getpixel((5, 5))[3] == 0 and im.getpixel((30, 5)) == (255, 0, 0, 255)
    pal = Image.new("P", (10, 10), 0)
    pal.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    pal.paste(1, (5, 0, 10, 10))
    working, _ = store.import_image(encode(pal, "GIF", transparency=0), "emoji.gif")
    with store.image(working.id) as im:
        assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0
        assert im.getpixel((7, 5)) == (255, 255, 255, 255)


def test_import_takes_the_first_frame_of_an_animation():
    store = ArtifactStore()
    working, original = store.import_image(gif3(), "dance.gif")
    assert (original.format, original.frames) == ("GIF", 3)
    assert (working.format, working.frames, working.width, working.height) == ("PNG", 1, 30, 20)
    with store.image(working.id) as im:
        assert im.getpixel((0, 0)) == (255, 0, 0)


def test_import_turns_a_phone_photo_upright():
    store = ArtifactStore()
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to show
    photo = encode(Image.new("RGB", (40, 20), "blue"), "JPEG", exif=exif)
    working, original = store.import_image(photo, "IMG_0001.jpg")
    assert (working.width, working.height) == (20, 40) and (original.width, original.height) == (20, 40)
    assert store.data(original.id) == photo  # the original bytes, EXIF included, unchanged


@pytest.mark.parametrize("name, label", [
    ("lincoln.png", "lincoln"), ("Old Photo é.JPG", "old_photo"), ("/home/u/Pictures/trump.jpeg", "trump"),
    ("../../etc/passwd", "passwd"), ("fetch.png", "fetch"), ("", "pasted"), ("日本.png", "pasted"),
    ("badshop_work/lincoln_work.png", "lincoln"), ("work.png", "work"),
])
def test_import_labels_are_slugified_file_stems(name, label):
    working, original = ArtifactStore().import_image(encode(Image.new("RGB", (1200, 10), "gray")), name)
    assert (original.label, working.label) == (label, f"{label}_work")


def test_import_refuses_bad_bytes_cleanly_and_stores_nothing(monkeypatch):
    store = ArtifactStore()
    png = encode(Image.new("RGB", (64, 64), "red"))
    for bad in (b"", b"GIF89a garbage", EPS, png[: len(png) // 2]):
        with pytest.raises(EngineError, match="isn't an image badshop can open") as e:
            store.import_image(bad, "notes.txt")
        assert e.value.message.startswith("notes.txt ") and "PNG, JPEG" in e.value.hint
    monkeypatch.setattr(artifacts, "MAX_IMPORT_PIXELS", 100)  # a 20x20 image stands in for a >100 Mpx one
    with pytest.raises(EngineError, match="too big") as e:
        store.import_image(encode(Image.new("RGB", (20, 20))), "")
    assert e.value.message.startswith("the pasted data is too big") and "megapixels" in e.value.hint
    assert store.ids() == []
