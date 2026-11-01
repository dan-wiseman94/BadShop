"""Reusable assets survive new sessions; directions survive replay and portable projects."""

import io
import json
import zipfile

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session import branches, project
from badshop.session.library import AssetDetails, AssetLibrary
from badshop.session.models import Source
from badshop.session.session import Session
from test_server_app import Client, Failed, imported, run
from test_server_app import env as env


def picture(size=(1300, 60)):
    out = io.BytesIO()
    Image.new("RGBA", size, (200, 40, 10, 255)).save(out, "PNG")
    return out.getvalue()


def test_library_preserves_original_provenance_and_cutout(tmp_path):
    first = Session.new()
    source = Source(kind="commons", page="https://example.org/photo", license="CC0", creator="Tester")
    image = first.import_image(picture(), "favorite", source)
    lib = AssetLibrary(tmp_path / "library")
    entry = lib.save(first, image.id, "My favorite", ["facing right", "head"],
                     AssetDetails(crop=(1, 2, 30, 40), faces=[{"head": [1, 2, 30, 40]}], notes="Useful"))
    # A new library instance and session do not depend on the original process's artifact store.
    fresh = AssetLibrary(tmp_path / "library")
    target = Session.new()
    restored = fresh.restore(target, entry["id"])
    assert restored["working"]["id"] == image.id
    assert restored["original"]["width"] == 1300
    assert target.artifacts.data(image.id) == first.artifacts.data(image.id)
    assert restored["working"]["source"]["license"] == "CC0"
    assert restored["entry"]["metadata"]["crop"] == [1, 2, 30, 40]
    assert "facing right" in target.data.transcript[-1]["content"]
    assert fresh.list("favorite", ["HEAD"])[0]["id"] == entry["id"]
    assert not fresh.list("nonexistent")
    fresh.update(entry["id"], name="Renamed", tags=["dog"])
    assert fresh.list("renamed", ["dog"])
    assert fresh.thumbnail(entry["id"])["mime"] == "image/png"
    fresh.remove(entry["id"])
    assert fresh.list() == []



def test_library_cutout_recovers_source_crop_and_unchanged_pixels(tmp_path):
    session = Session.new()
    source = Source(kind="url", url="https://example.com/image.png", creator="A photographer")
    base = session.import_image(picture((100, 100)), "source", source)
    step = session.run(session.propose("cutout", {"image": base.id, "box": [10, 10, 60, 60],
                                                 "no_ai": True}, "user").id)
    lib = AssetLibrary(tmp_path)
    entry = lib.save(session, step.outputs[0], "head", [], AssetDetails())
    assert entry["metadata"]["crop"] == [10, 10, 60, 60]
    assert entry["artifact"]["source"]["creator"] == "A photographer"
    assert entry["original"]["id"] == base.id
    target = Session.new()
    restored = lib.restore(target, entry["id"])
    assert target.artifacts.data(restored["working"]["id"]) == session.artifacts.data(step.outputs[0])
    reopened = project.open_project(project.save(target, tmp_path / "reused.badshop"))
    assert reopened.artifacts.meta[step.outputs[0]].source == source


def test_library_refuses_corrupt_data_without_partial_import(tmp_path):
    session = Session.new()
    im = session.import_image(picture(), "example")
    lib = AssetLibrary(tmp_path)
    entry = lib.save(session, im.id, "Saved", [], AssetDetails())
    (tmp_path / f"{im.id}.png").write_bytes(b"corrupt")
    target = Session.new()
    with pytest.raises(EngineError, match="hash"):
        lib.restore(target, entry["id"])
    assert not target.artifacts.ids()
    with pytest.raises(EngineError, match="invalid library"):
        lib.get("../../etc/passwd")


def test_branches_keep_independent_replay_and_survive_save(tmp_path):
    session = Session.new()
    im = session.import_image(picture((40, 40)), "base")
    first = session.run(session.propose("filter", {"image": im.id, "names": ["invert"]}, "user").id)
    original_pixels = session.artifacts.data(first.outputs[0])
    branches.create(session, "Poster", first.id)
    poster = session.data.active_branch_id
    original = next(b.id for b in session.data.branches.values() if b.name == "Original")
    session.edit(first.id, {"image": im.id, "names": ["grayscale"]})
    session.replay_from(first.id)
    poster_pixels = session.artifacts.data(session.step(first.id).outputs[0])
    assert poster_pixels != original_pixels
    branches.switch(session, original)
    assert session.artifacts.data(session.step(first.id).outputs[0]) == original_pixels
    saved = project.save(session, tmp_path / "directions.badshop")
    restored = project.open_project(saved)
    assert restored.data.schema_ == 2
    assert branches.listing(restored)["active_id"] == original
    branches.switch(restored, poster)
    assert restored.artifacts.data(restored.step(first.id).outputs[0]) == poster_pixels
    branches.rename(restored, poster, "New title")
    assert branches.listing(restored)["branches"][1]["name"] == "New title"
    with pytest.raises(EngineError, match="switch"):
        branches.remove(restored, poster)
    branches.remove(restored, original)
    assert len(restored.data.branches) == 1


def test_v1_project_migrates_and_bad_branch_is_refused(tmp_path):
    path = project.save(Session.new(), tmp_path / "legacy.badshop")
    with zipfile.ZipFile(path) as z:
        payload = json.loads(z.read("session.json"))
    payload.update(schema=1)
    payload.pop("branches")
    payload.pop("active_branch_id")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("session.json", json.dumps(payload))
    opened = project.open_project(path)
    assert opened.data.schema_ == 2 and opened.data.branches == {}
    branches.create(opened, "Alt")
    broken = opened.data.model_dump(mode="json", by_alias=True)
    broken["branches"][opened.data.active_branch_id]["artifact_ids"] = ["f" * 64]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("session.json", json.dumps(broken))
    with pytest.raises(EngineError, match="missing artifact"):
        project.open_project(path)


@pytest.mark.usefixtures("env")
def test_server_library_and_branch_revisions():
    async def body(app):
        c = Client(app)
        image = await imported(c)
        saved = await c.call("library.save", artifact_id=image, name="Lincoln", tags=["portrait"])
        before = await c.call("session.get")
        created = await c.call("branches.create", name="Poster", expected_revision=before["document_revision"])
        assert created["unsaved_changes"]
        # Branching retains the original even when the document had never been saved.
        listing = await c.call("branches.list")
        assert len(listing["branches"]) == 2
        with pytest.raises(Failed, match="changed"):
            await c.call("branches.switch", id=listing["branches"][0]["id"],
                         expected_revision=before["document_revision"])
        await c.call("session.new")
        restored = await c.call("library.import", id=saved["id"])
        assert restored["working"]["id"] == image
        cli = Client(app, "cli:codex")
        with pytest.raises(Failed):
            await cli.call("library.list")
        with pytest.raises(Failed):
            await cli.call("branches.create", name="forbidden")
    run(body)


def test_branch_cut_hides_future_outputs_and_new_imports_stay_local(tmp_path):
    session = Session.new()
    im = session.import_image(picture((40, 40)), "base")
    first = session.run(session.propose("filter", {"image": im.id, "names": ["invert"]}, "user").id)
    second = session.run(session.propose("filter", {"image": first.outputs[0], "names": ["grayscale"]}, "user").id)
    future = second.outputs[0]
    branches.create(session, "Earlier", first.id)
    earlier = session.data.active_branch_id
    original = next(b.id for b in session.data.branches.values() if b.name == "Original")
    assert future not in session.visible_artifact_ids()
    local = session.import_image(picture((50, 50)), "local")
    assert local.id in session.visible_artifact_ids()
    branches.switch(session, original)
    assert future in session.visible_artifact_ids()
    assert local.id not in session.visible_artifact_ids()
    restored = project.open_project(project.save(session, tmp_path / "all.badshop"))
    assert local.id not in restored.visible_artifact_ids()
    branches.switch(restored, earlier)
    assert local.id in restored.visible_artifact_ids()
    assert future not in restored.visible_artifact_ids()


def test_active_branch_edits_after_create_survive_save_and_next_switch(tmp_path):
    session = Session.new()
    im = session.import_image(picture((40, 40)), "base")
    branches.create(session, "Alternative")
    alt = session.data.active_branch_id
    original = next(b.id for b in session.data.branches.values() if b.name == "Original")
    edit = session.run(session.propose("filter", {"image": im.id, "names": ["invert"]}, "user").id)
    restored = project.open_project(project.save(session, tmp_path / "active.badshop"))
    assert restored.data.steps[0].outputs == edit.outputs
    branches.switch(restored, original)
    assert restored.data.steps == []
    branches.switch(restored, alt)
    assert restored.data.steps[0].outputs == edit.outputs


def test_library_import_visible_on_branch_and_metadata_survives_reopen(tmp_path):
    source = Session.new()
    image = source.import_image(picture((33, 44)), "head")
    library = AssetLibrary(tmp_path / "library")
    entry = library.save(source, image.id, "Head", ["facing right"], AssetDetails(notes="expressive"))
    target = Session.new()
    branches.create(target, "New")
    library.restore(target, entry["id"])
    assert image.id in target.visible_artifact_ids()
    opened = project.open_project(project.save(target, tmp_path / "import.badshop"))
    assert image.id in opened.visible_artifact_ids()
    assert "facing right" in opened.data.transcript[-1]["content"]
    assert opened.data.transcript[-1]["role"] == "user"
