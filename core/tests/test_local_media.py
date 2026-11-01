import shutil
import subprocess

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session import branches, project
from badshop.session.local_collection import LocalCollections
from badshop.session.media import MediaSources
from badshop.session.session import Session
from badshop.server.media_api import register
from badshop.server.rpc import FORBIDDEN
from test_server_app import Client, Failed, run, env as env


def gif(path):
    images = [Image.new("RGB", (80, 60), color) for color in ("red", "green", "blue")]
    images[0].save(path, save_all=True, append_images=images[1:], duration=[100, 200, 300], loop=0)


def test_gif_timecodes_and_frozen_import_survive_source_removal(tmp_path):
    source = tmp_path / "reaction.gif"
    gif(source)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "video", count=3)
    assert [c["time_s"] for c in preview["candidates"]] == [0, .1, .3]
    assert preview["sheet_data_url"].startswith("data:image/png;base64,")
    source.unlink()
    session = Session.new()
    result = media.import_selected(session, preview["id"], ["1"])
    meta = session.artifacts.meta[result["artifacts"][0]["id"]]
    assert session.artifacts.image(meta.id).getpixel((1, 1))[:3] == (0, 128, 0)
    assert "0.100s" in meta.source.title
    file = tmp_path / "saved.badshop"
    project.save(session, file)
    restored = project.open_project(file)
    assert "source_sha256" in restored.data.transcript[-1]["content"]
    assert "time_s" in restored.data.transcript[-1]["content"]


def test_crop_keeps_page_and_original_pixels(tmp_path):
    source = tmp_path / "scan.png"
    im = Image.new("RGB", (80, 60), "blue")
    im.save(source)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "document")
    session = Session.new()
    branches.create(session, "Crop")
    result = media.import_selected(session, preview["id"], ["0"], crop=(5, 10, 35, 40))
    meta = session.artifacts.meta[result["artifacts"][0]["id"]]
    assert (meta.width, meta.height) == (30, 30)
    assert session.artifacts.meta[meta.original_id].width == 80
    assert meta.id in session.visible_artifact_ids()
    assert "Page 1" in meta.source.title
    assert result["provenance"]["crop"] == (5, 10, 35, 40)
    assert session.data.steps[-1].tool == "cutout"
    assert session.data.steps[-1].params["box"] == [5, 10, 35, 40]


def test_media_invalid_selection_and_crop_do_not_mutate(tmp_path):
    source = tmp_path / "reaction.gif"
    gif(source)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "video", count=3)
    for ids, options in [(["../secret"], {}), (["0"], {"crop": [-1, 0, 20, 20]}),
                         (["0"], {"animate": True}), (["0", "0"], {})]:
        session = Session.new()
        with pytest.raises(EngineError):
            media.import_selected(session, preview["id"], ids, **options)
        assert not session.artifacts.ids()


def test_selected_frames_use_existing_animate_tool(tmp_path):
    source = tmp_path / "reaction.gif"
    gif(source)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "video", count=3)
    session = Session.new()
    result = media.import_selected(session, preview["id"], ["0", "1", "2"], animate=True, delay=80)
    assert session.data.steps[-1].tool == "animate"
    assert session.data.steps[-1].params["delay"] == 80
    assert result["artifacts"][0]["frames"] == 3


def test_changed_cached_frame_is_rejected(tmp_path):
    source = tmp_path / "scan.png"
    Image.new("RGB", (30, 30), "red").save(source)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "document")
    (media.root / preview["id"] / "0.png").write_bytes(b"changed")
    with pytest.raises(EngineError, match="changed"):
        media.import_selected(Session.new(), preview["id"], ["0"])


def test_missing_decoder_is_actionable(tmp_path, monkeypatch):
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(EngineError, match="pdftoppm is not installed"):
        MediaSources(tmp_path / "cache").preview(str(pdf), "document")


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="optional PDF renderer")
def test_real_pdf_page_and_region(tmp_path):
    path = tmp_path / "pages.pdf"
    Image.new("RGB", (80, 60), "red").save(path, "PDF", save_all=True,
            append_images=[Image.new("RGB", (80, 60), "blue")])
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(path), "document", page=2)
    assert preview["candidates"][0]["page"] == 2
    result = media.import_selected(Session.new(), preview["id"], ["0"], crop=(10, 10, 30, 30))
    assert result["artifacts"][0]["width"] == 20


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="optional video tools")
def test_real_video_frames(tmp_path):
    source = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=80x60:d=1",
                    "-c:v", "mpeg4", str(source)], check=True, timeout=20)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "video", count=3)
    assert len(preview["candidates"]) == 3
    assert preview["candidates"][1]["time_s"] > 0


def test_collection_index_dedup_search_and_roundtrip(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    Image.new("RGB", (40, 30), "red").save(photos / "dog.png")
    shutil.copyfile(photos / "dog.png", photos / "same.png")
    Image.new("RGB", (40, 30), "blue").save(photos / ".private.png")
    collections = LocalCollections(tmp_path / "index")
    summary = collections.index(str(photos))
    assert summary["count"] == 2 and summary["duplicates"] == 1
    entry = collections.search(summary["id"], "dog")[0]
    assert "relative" not in entry
    collections.update(summary["id"], entry["id"], ["disappointed", "dog"], "Facing left in an office")
    fresh = LocalCollections(tmp_path / "index")
    assert fresh.search(summary["id"], "disappointed office")[0]["id"] == entry["id"]
    session = Session.new()
    result = fresh.restore(session, summary["id"], entry["id"])
    assert result["working"]["source"]["kind"] == "local-collection"
    assert "disappointed" in session.data.transcript[-1]["content"]
    assert str(photos) not in session.data.transcript[-1]["content"]
    fresh.index(str(photos))
    assert fresh.search(summary["id"], "office")


def test_collection_no_symlink_escape_and_changed_file_rejected(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    outside = tmp_path / "private.png"
    Image.new("RGB", (40, 30), "red").save(outside)
    (photos / "link.png").symlink_to(outside)
    (photos / "outside").symlink_to(tmp_path, target_is_directory=True)
    Image.new("RGB", (40, 30), "blue").save(photos / "dog.png")
    collections = LocalCollections(tmp_path / "index")
    summary = collections.index(str(photos))
    assert summary["count"] == 1
    entry = collections.search(summary["id"])[0]
    Image.new("RGB", (40, 30), "green").save(photos / "dog.png")
    with pytest.raises(EngineError, match="changed"):
        collections.restore(Session.new(), summary["id"], entry["id"])
    collections.index(str(photos))
    (photos / "dog.png").unlink()
    (photos / "dog.png").symlink_to(outside)
    with pytest.raises(EngineError, match="link"):
        collections.restore(Session.new(), summary["id"], entry["id"])


def test_user_only_media_rpc(env):
    async def scenario(app):
        if "media.preview" not in app.dispatcher.names():
            register(app)
        client = Client(app, "agent:test")
        with pytest.raises(Failed) as failure:
            await client.call("media.preview", path="/private/clip.mp4", kind="video")
        assert failure.value.code == FORBIDDEN
    run(scenario)


def test_reindex_drops_descriptions_when_pixels_change(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    path = photos / "dog.png"
    Image.new("RGB", (40, 30), "red").save(path)
    collection = LocalCollections(tmp_path / "index")
    summary = collection.index(str(photos))
    entry = collection.search(summary["id"])[0]
    collection.update(summary["id"], entry["id"], ["dog"], "Dog facing left")
    Image.new("RGB", (40, 30), "blue").save(path)
    collection.index(str(photos))
    changed = collection.search(summary["id"])[0]
    assert changed["tags"] == [] and changed["description"] == ""


def test_full_resolution_noisy_scan_can_import_its_own_preview(tmp_path):
    import numpy as np
    source = tmp_path / "scan.png"
    Image.fromarray(np.random.default_rng(123).integers(0, 256, (1000, 1000, 3), dtype=np.uint8)).save(source)
    media = MediaSources(tmp_path / "cache")
    preview = media.preview(str(source), "document")
    assert (media.root / preview["id"] / "preview.json").stat().st_size < 10000
    assert media.import_selected(Session.new(), preview["id"], ["0"])["artifacts"]


def test_media_and_collection_import_refuse_pending_agent_turn(env):
    async def scenario(app):
        if "media.import" not in app.dispatcher.names():
            register(app)
        client = Client(app)
        app._starting = True
        for method, params in (("media.import", {"preview_id": "a" * 32, "candidate_ids": ["0"]}),
                               ("collections.import", {"collection_id": "a" * 32, "id": "b" * 32})):
            with pytest.raises(Failed, match="still working"):
                await client.call(method, **params)
        assert not app.session.data.transcript
        app._starting = False
    run(scenario)
