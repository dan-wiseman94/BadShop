import io
import json
import zipfile

import pytest
from PIL import Image, PngImagePlugin

from badshop.engine.errors import EngineError
from badshop.session import branches, project, recipes, remix
from badshop.session.models import Message, Part, Source
from badshop.session.session import Session


def picture(color="red"):
    out = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "private-photo-metadata")
    Image.new("RGB", (48, 36), color).save(out, "PNG", pnginfo=metadata)
    return out.getvalue()


def test_shared_remix_opens_edits_and_excludes_private_dependencies(tmp_path):
    session = Session.new(output_dir=tmp_path)
    session.data.provider_profile_id = "private-provider"
    session.data.messages.append(Message(id="m1", role="user", content=[Part(type="text", text="private-chat")]))
    session.data.transcript = [{"text": "private-transcript"}]
    source, original = session.artifacts.import_image(picture(), "private-filename.png", Source(kind="url", url="https://example.com/private-source"))
    branches.create(session, "private-other-branch")
    other = session.run_tool("text", {"image": source.id, "text": "UNRELATED", "size": 10}, "user")
    assert other.status == "done"
    branches.switch(session, next(b.id for b in session.data.branches.values() if b.name == "Original"))
    step = session.run_tool("layout", {"template": "trading-card", "images": [source.id], "title": "Keep this joke", "captions": ["Hello"]}, "user")
    assert step.status == "done"
    before = session.data.model_dump_json()
    preview = remix.inspect(session, step.outputs[0])
    assert set(preview["artifact_ids"]) == {source.id, step.outputs[0]}
    path = remix.export(session, step.outputs[0])
    assert session.data.model_dump_json() == before
    with zipfile.ZipFile(path) as archive:
        payload = archive.read("session.json")
        assert b"private-" not in payload and b"UNRELATED" not in payload
        assert original.id not in json.loads(payload)["artifacts"]
    loaded = project.open_project(path, output_dir=tmp_path)
    assert len(loaded.data.steps) == 1 and not loaded.data.branches and not loaded.data.messages
    assert loaded.data.provider_profile_id is None and not loaded.data.transcript
    for aid in loaded.artifacts.ids():
        assert loaded.artifacts.meta[aid].original_id is None
        with loaded.artifacts.image(aid) as im:
            assert "Comment" not in im.info
    with session.artifacts.image(step.outputs[0]) as expected, loaded.artifacts.image(loaded.data.steps[0].outputs[0]) as actual:
        assert actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
    loaded.edit("s1", {**loaded.data.steps[0].params, "title": "A new joke"})
    assert loaded.replay_from("s1")[0].status == "done"
    assert remix.export(session, step.outputs[0]) != path
    credited = project.open_project(remix.export(session, step.outputs[0], True), output_dir=tmp_path)
    assert recipes.credits(credited, credited.data.steps[0].outputs[0])["sources"][0]["url"] == "https://example.com/private-source"


def test_remix_strips_animation_comments_and_preserves_frames(tmp_path):
    session = Session.new(output_dir=tmp_path)
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    blob = io.BytesIO()
    frames[0].save(blob, "GIF", save_all=True, append_images=frames[1:], duration=[100, 200], comment=b"private", loop=0)
    source = session.artifacts.add(blob.getvalue(), "private.gif")
    loaded = project.open_project(remix.export(session, source.id), output_dir=tmp_path)
    result = next(iter(loaded.artifacts.meta.values()))
    assert result.frames == 2
    for index, expected in enumerate(frames):
        with loaded.artifacts.image(result.id, index) as actual:
            assert "comment" not in actual.info
            assert actual.convert("RGB").tobytes() == expected.tobytes()


def test_remix_refuses_invisible_branch_result(tmp_path):
    session = Session.new(output_dir=tmp_path)
    source = session.artifacts.add(picture(), "start")
    branches.create(session, "other")
    result = session.run_tool("transform", {"image": source.id, "flip_horizontal": True}, "user")
    # A distinct picture is needed even when a transform happens to be identical.
    branches.switch(session, next(b.id for b in session.data.branches.values() if b.name == "Original"))
    hidden = session.artifacts.add(picture("blue"), "hidden", produced_by=result.id)
    with pytest.raises(EngineError, match="current direction"):
        remix.export(session, hidden.id)
    assert not list(tmp_path.glob("*.badshop"))


def test_remix_refuses_nonportable_font_before_writing(tmp_path):
    from badshop.session.models import Step
    session = Session.new(output_dir=tmp_path)
    source = session.artifacts.add(picture(), "source")
    output = session.artifacts.add(picture("blue"), "text", produced_by="s1")
    session.data.steps.append(Step(id="s1", index=1, tool="text", actor="user", status="done",
                                   params={"image": source.id, "text": "Hello", "font": "C:/Users/Private/custom.ttf"}, outputs=[output.id]))
    with pytest.raises(EngineError, match="custom font"):
        remix.export(session, output.id)
    assert not list(tmp_path.glob("*.badshop"))


def test_normalized_import_does_not_acquire_a_later_producer(tmp_path):
    session = Session.new(output_dir=tmp_path)
    source = session.artifacts.add(picture(), "input")
    text = session.run_tool("text", {"image": source.id, "text": "Hello", "size": 10}, "user")
    canvas = session.run_tool("canvas", {"width": 48, "height": 36, "background": "red"}, "user")
    assert text.status == canvas.status == "done"
    pasted = session.run_tool("paste", {"base": text.outputs[0], "piece": canvas.outputs[0], "at": [0, 0], "width": 10}, "user")
    assert pasted.status == "done"
    reopened = project.open_project(remix.export(session, pasted.outputs[0]), output_dir=tmp_path)
    assert reopened.data.steps[0].params["image"] == reopened.data.steps[1].outputs[0]
    reopened.edit("s1", {**reopened.data.steps[0].params, "text": "Changed"})
    assert all(step.status == "done" for step in reopened.replay_from("s1"))
