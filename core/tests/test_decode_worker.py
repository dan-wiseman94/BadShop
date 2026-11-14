"""Compressed image bytes must be decoded outside the desktop core process."""
import io
import os
import tempfile
import threading

from PIL import Image
import psutil
import pytest

from badshop.engine.errors import EngineError
from badshop.session import artifacts, branches
from badshop.session.artifacts import ArtifactStore
from badshop.session.project import open_project, save
from badshop.session.session import Session
from badshop.session.library import AssetDetails, AssetLibrary
from badshop.session.worker import WorkerExecutor


def encoded(image, format="PNG", **kw):
    buf = io.BytesIO()
    image.save(buf, format, **kw)
    return buf.getvalue()


def test_worker_import_animation_project_and_collection_keep_pixels_without_parent_decoder(tmp_path, monkeypatch):
    red, blue = [Image.new("RGBA", (20, 15), color) for color in ("red", "blue")]
    png = encoded(red)
    gif = encoded(red, "GIF", save_all=True, append_images=[blue], duration=100, loop=0)
    expected = ArtifactStore()
    expected_work, _ = expected.import_image(gif, "dance.gif")
    monkeypatch.setattr(artifacts, "_decode", lambda *args: pytest.fail("compressed decode in parent"))
    with WorkerExecutor(timeout_s=30, max_rss_mb=1024) as worker:
        session = Session.new(decoder=worker.decode)
        work = session.import_image(gif, "dance.gif")
        assert session.artifacts.data(work.id) == expected.data(expected_work.id)
        original = session.artifacts.meta[work.original_id]
        assert original.frames == 2
        with session.artifacts.image(original.id, 1) as image:
            assert image.convert("RGB").getpixel((0, 0)) == (0, 0, 255)
        path = tmp_path / "dance.badshop"
        branches.create(session, "Alternate")
        save(session, path)
        restored = open_project(path, decoder=worker.decode)
        assert restored.artifacts.data(original.id) == gif
        assert restored.artifacts.data(work.id) == expected.data(work.id)
        with restored.artifacts.image(original.id, 1) as image:
            assert image.convert("RGB").getpixel((0, 0)) == (0, 0, 255)
        assert restored.import_image(png, "after-reopen.png").width == 20
        folder = tmp_path / "pictures"
        folder.mkdir()
        (folder / "red.png").write_bytes(png)
        result = worker.media("index", str(tmp_path / "index"), path=str(folder))
        assert result["count"] == 1 and not result["warnings"]
        preview = worker.media("preview", str(tmp_path / "preview"), path=str(folder / "red.png"), kind="document")
        assert preview["candidates"][0]["width"] == 20
        before = session.artifacts.ids()
        with pytest.raises(EngineError, match="isn't an image"):
            session.import_image(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage", "hostile.eps")
        assert session.artifacts.ids() == before
        assert session.import_image(png, "recovery.png").width == 20
        pid = worker.pid
        assert pid != os.getpid()
    assert not psutil.pid_exists(pid)


def test_aggregate_import_limit_is_atomic_and_counts_unique_bytes(monkeypatch):
    store = ArtifactStore()
    first = encoded(Image.new("RGB", (10, 10), "red"))
    kept = store.add(first, "kept")
    monkeypatch.setattr(artifacts, "MAX_STORED_BYTES", len(first) + 1)
    assert store.add(first, "same") is kept
    with pytest.raises(EngineError, match="storage limit"):
        store.import_image(encoded(Image.new("RGB", (1500, 10), "blue")), "too much")
    assert store.ids() == [kept.id] and store.data(kept.id) == first


def test_malformed_phone_image_is_refused_without_changing_document():
    session = Session.new()
    kept = session.import_image(encoded(Image.new("RGB", (10, 10), "red")), "kept")
    with pytest.raises(EngineError, match="isn't an image") as refused:
        session.import_image(b"unsupported phone bytes", "holiday.heic")
    assert "HEIC/HEIF" in refused.value.hint
    assert session.artifacts.ids() == [kept.id]


def test_heic_worker_import_and_project_keep_original_and_decoded_pixels(tmp_path, monkeypatch):
    source = Image.new("RGB", (64, 32), (30, 140, 220))
    raw = encoded(source, "HEIF", quality=-1)
    expected = ArtifactStore()
    work, original = expected.import_image(raw, "phone.heic")
    assert original.format == "HEIF"
    assert original.mime == "image/heif"
    monkeypatch.setattr(artifacts, "_decode", lambda *args: pytest.fail("HEIC decoded in parent"))
    with WorkerExecutor(timeout_s=30, max_rss_mb=1024) as worker:
        session = Session.new(decoder=worker.decode, executor=worker)
        imported = session.import_image(raw, "phone.heic")
        assert session.artifacts.data(imported.id) == expected.data(work.id)
        assert session.artifacts.data(imported.original_id) == raw
        file = tmp_path / "phone.badshop"
        save(session, file)
        restored = open_project(file, decoder=worker.decode, executor=worker)
        assert restored.artifacts.data(imported.original_id) == raw
        assert restored.artifacts.data(imported.id) == expected.data(work.id)
        step = restored.run_tool("text", {"image": imported.original_id, "text": "Hi",
            "font": "bundled", "size": 8, "margin": 1}, "user")
        assert step.status == "done"
        pid = worker.pid
    assert not psutil.pid_exists(pid)


def test_library_restore_storage_failure_keeps_existing_document(tmp_path, monkeypatch):
    source = Session.new()
    imported = source.import_image(encoded(Image.new("RGB", (1500, 10), "blue")), "wide")
    library = AssetLibrary(tmp_path)
    entry = library.save(source, imported.id, "Wide", [], AssetDetails())
    target = Session.new()
    kept = target.import_image(encoded(Image.new("RGB", (10, 10), "red")), "kept")
    before = target.data.model_dump()
    original = source.artifacts.data(imported.original_id)
    monkeypatch.setattr(artifacts, "MAX_STORED_BYTES", len(target.artifacts.data(kept.id)) + len(original))
    with pytest.raises(EngineError, match="storage limit"):
        library.restore(target, entry["id"])
    assert target.artifacts.ids() == [kept.id]
    assert target.data.model_dump() == before


def test_multi_output_storage_failure_rolls_back_only_new_artifacts(monkeypatch):
    image = Image.new("RGB", (20, 10), "red")
    image.paste("blue", (10, 0, 20, 10))
    session = Session.new()
    kept = session.import_image(encoded(image), "two tiles")
    first_tile = encoded(image.crop((0, 0, 10, 10)).convert("RGBA"))
    monkeypatch.setattr(artifacts, "MAX_STORED_BYTES", len(session.artifacts.data(kept.id)) + len(first_tile))
    step = session.run_tool("slice_sheet", {"image": kept.id, "columns": 2, "rows": 1}, "user")
    assert step.status == "error" and "storage limit" in step.error.message
    assert step.outputs == [] and session.artifacts.ids() == [kept.id]


@pytest.mark.parametrize("stop", ["timeout", "cancel"])
def test_media_worker_timeout_removes_owned_source_copy_and_child(tmp_path, monkeypatch, stop):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    # Inject a stalled native-decoder stand-in into the real spawned worker.
    # No production test hook: spawn inherits this test-only import path.
    pidfile = tmp_path / "decoder.pid"
    (tmp_path / "av.py").write_text(
        "import os,time,pathlib\nclass FFmpegError(Exception): pass\n"
        f"def open(*args, **kwargs):\n    pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n    time.sleep(60)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"private video test fixture")
    signal = threading.Event()
    with WorkerExecutor(timeout_s=1 if stop == "timeout" else 30, max_rss_mb=1024) as worker:
        timer = threading.Timer(1.5, signal.set) if stop == "cancel" else None
        if timer:
            timer.start()
        try:
            with pytest.raises(EngineError, match="took longer|stopped by the user"):
                worker.media("preview", str(tmp_path / "previews"), path=str(source), kind="video", cancel=signal)
        finally:
            if timer:
                timer.cancel()
                timer.join()
        assert not list(scratch.glob("badshop-media-*"))
        assert pidfile.exists(), "must enter the decoder in the actual worker before timeout"
        try:
            assert psutil.Process(int(pidfile.read_text())).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass  # either reaped or dead awaiting the OS reaper; never still executing
    assert source.read_bytes() == b"private video test fixture"
