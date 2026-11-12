import io

import pytest
from PIL import Image, ImageFont

from badshop.engine.errors import EngineError
from badshop.session import project
from badshop.session import branches
from badshop.engine.transform import TransformParams, transform
from badshop.session.session import Session


def test_preview_preserves_project_and_matches_committed_pixels(tmp_path):
    session = Session.new()
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buffer, "PNG")
    source = session.import_image(buffer.getvalue(), "source")
    step = session.run_tool("filter", {"image": source.id, "names": ["invert"]}, "user")
    before = session.data.model_dump_json()
    changes = list(session.changes)
    events = []
    session.emit = lambda *args: events.append(args)
    session.on_change = lambda: events.append("changed")
    params = {**step.params, "names": ["grayscale"]}
    preview = session.preview_edit(step.id, params)
    assert preview
    assert session.data.model_dump_json() == before
    assert session.changes == changes
    assert events == []
    session.edit(step.id, params)
    session.replay_from(step.id)
    assert session.artifacts.data(step.outputs[0]) == preview[0].data
    path = tmp_path / "preview.badshop"
    project.save(session, path)
    reopened = project.open_project(path)
    assert reopened.artifacts.data(reopened.step(step.id).outputs[0]) == preview[0].data


def test_preview_refuses_network_and_preserves_state():
    session = Session.new()
    step = session.propose("wiki", {"title": "test"}, "user")
    session.reject(step.id)
    before = session.data.model_dump_json()
    with pytest.raises(EngineError, match="local image tool"):
        session.preview_edit(step.id, step.params)
    assert session.data.model_dump_json() == before


def test_transform_preserves_exact_pixels_and_rejects_bad_crop():
    image = Image.new("RGB", (2, 1))
    image.putdata([(255, 0, 0), (0, 0, 255)])
    params = TransformParams(image="source", width=4, flip_horizontal=True, rotate=90)
    result = transform(params, image).outputs[0].image
    assert result.size == (2, 4)
    assert [result.getpixel((x, y)) for y in range(result.height) for x in range(result.width)] == [
        (255, 0, 0)] * 4 + [(0, 0, 255)] * 4
    with pytest.raises(EngineError, match="crop"):
        transform(TransformParams(image="source", crop=[0, 0, 3, 1]), image)


def test_exact_caption_fit_preserves_words_and_refuses_clipping(monkeypatch):
    from badshop.engine import text
    monkeypatch.setattr(text, "load_font", lambda style, size, explicit: (ImageFont.load_default(size=size), "fixture"))
    params = text.TextParams(image="source", text="Hello\nWORLD", style="paint", size=120, margin=3, fit_exact=True)
    result = text.caption(params, Image.new("RGB", (100, 80), "white"))
    assert result.outputs[0].image.size == (100, 80)
    assert params.text == "Hello\nWORLD"
    with pytest.raises(EngineError, match="clip words"):
        text.caption(params.model_copy(update={"at": [0, 0]}), Image.new("RGB", (100, 80), "white"))


def test_checkpoint_is_preserved_when_visited_and_keeps_change_notes():
    session = Session.new()
    session.changes = ["the user adjusted placement"]
    branches.begin_turn(session)
    assert session.changes == ["the user adjusted placement"]
    checkpoint = session.data.undo_branch_id
    attempt = session.data.active_branch_id
    branches.switch(session, checkpoint)
    assert session.data.active_branch_id != checkpoint
    session.data.creative.seed = 42
    branches.switch(session, attempt)
    branches.undo_turn(session)
    assert session.data.creative.seed == 1
    assert attempt in session.data.branches


def test_bypass_keeps_distinct_outputs_and_replays_after_reopening(tmp_path):
    session = Session.new()
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "PNG")
    source = session.import_image(buffer.getvalue(), "source")
    first = session.run_tool("filter", {"image": source.id, "names": ["invert"]}, "user")
    second = session.run_tool("filter", {"image": source.id, "names": ["invert"]}, "user")
    first.bypassed = second.bypassed = True
    session.edit(first.id, first.params)
    session.replay_from(first.id)
    assert first.outputs != second.outputs
    assert session.artifacts.image(first.outputs[0]).getpixel((0, 0)) == (255, 0, 0)
    assert project.export_recipe(session)["steps"][0][0] == "transform"
    with pytest.raises(EngineError, match="enable this effect"):
        session.preview_edit(first.id, first.params)
    path = project.save(session, tmp_path / "bypass.badshop")
    reopened = project.open_project(path)
    reopened.step(first.id).bypassed = False
    reopened.edit(first.id, first.params)
    reopened.replay_from(first.id)
    assert reopened.artifacts.image(reopened.step(first.id).outputs[0]).getpixel((0, 0)) == (0, 255, 255)
    assert reopened.artifacts.image(reopened.step(second.id).outputs[0]).getpixel((0, 0)) == (255, 0, 0)
