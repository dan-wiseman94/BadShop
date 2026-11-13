import io

from PIL import Image

from badshop.session import project
from badshop.session.local_collection import LocalCollections
from badshop.session.session import Session


def test_avif_original_survives_edit_save_and_reopen(tmp_path):
    blob = io.BytesIO()
    Image.new("RGB", (80, 60), "purple").save(blob, "AVIF")
    session = Session.new(output_dir=tmp_path)
    working, original = session.artifacts.import_image(blob.getvalue(), "phone.avif")
    assert original.format == "AVIF" and working.format == "PNG"
    step = session.run_tool("layout", {"template": "achievement", "images": [working.id], "title": "Imported!"}, "user")
    assert step.status == "done"
    reopened = project.open_project(project.save(session, tmp_path / "avif.badshop"), output_dir=tmp_path)
    assert reopened.artifacts.data(original.id) == blob.getvalue()
    assert reopened.artifacts.data(step.outputs[0]) == session.artifacts.data(step.outputs[0])


def test_avif_folder_index_search_and_restore(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    Image.new("RGB", (80, 60), "orange").save(photos / "my-pet.avif", "AVIF")
    collections = LocalCollections(tmp_path / "index")
    summary = collections.index(str(photos))
    assert summary["count"] == 1 and summary["warnings"] == []
    hits = collections.search(summary["id"], "pet")
    assert len(hits) == 1 and hits[0]["thumbnail_data_url"].startswith("data:image/png;")
    session = Session.new(output_dir=tmp_path)
    restored = collections.restore(session, summary["id"], hits[0]["id"])
    assert restored["original"]["format"] == "AVIF"
    assert session.artifacts.data(restored["original"]["id"]) == (photos / "my-pet.avif").read_bytes()
