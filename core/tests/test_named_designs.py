import io
import threading

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session import recipes
from badshop.session.session import Session
from badshop.server.settings import Settings, load_settings, save_settings


def image(session, color):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    return session.import_image(buf.getvalue(), color).id


def test_capture_preserves_distinct_picture_roles_and_portable_library(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path))
    session = Session.new()
    red, blue = image(session, "red"), image(session, "blue")
    step = session.run_tool("paste", {"base": red, "piece": blue, "at": [0, 0], "width": 20}, "user")
    design = recipes.capture(session, step.id)
    assert design.steps[0].params["base"] == "$input:base"
    assert design.steps[0].params["piece"] == "$input:piece"
    save_settings(Settings(saved_designs=[design.model_dump()]))
    other = Session.new()
    green, yellow = image(other, "green"), image(other, "yellow")
    restored = recipes.Recipe.model_validate(load_settings().saved_designs[0])
    result = recipes.run(other, restored, [{"base": green, "piece": yellow}], threading.Event())
    assert not result["errors"]
    output = other.artifacts.image(result["rows"][0]["output_id"])
    assert output.getpixel((5, 5))[:3] == (255, 255, 0)
    assert output.getpixel((30, 30))[:3] == (0, 128, 0)


def test_named_text_defaults_row_errors_and_retry_keep_completed_outputs():
    session = Session.new()
    source = image(session, "red")
    design = recipes.Recipe(version=2, name="Labels", inputs={"picture": {"kind": "image"},
        "words": {"kind": "text", "default": "Default"}}, steps=[{"tool": "text", "params": {
            "image": "$input:picture", "text": "$text:words", "size": 6, "margin": 1, "preserve_case": True}}])
    result = recipes.run(session, design, [{"picture": source}, {}, {"picture": source, "words": "Next"}], threading.Event())
    assert [row["status"] for row in result["rows"]] == ["done", "error", "done"]
    assert session.data.steps[0].params["text"] == "Default"
    assert session.data.steps[1].params["text"] == "Next"
    kept = session.artifacts.data(result["rows"][0]["output_id"])
    retry = recipes.run(session, design, [{"picture": source, "words": "Fixed"}], threading.Event())
    assert retry["rows"][0]["status"] == "done"
    assert session.artifacts.data(result["rows"][0]["output_id"]) == kept


def test_named_batch_cancellation_marks_unfinished_rows_and_preserves_bytes():
    session = Session.new()
    source = image(session, "red")
    design = recipes.Recipe(version=2, name="Sizes", inputs={"picture": {"kind": "image"}},
        steps=[{"tool": "transform", "params": {"image": "$input:picture", "width": 20}}])
    cancel = threading.Event()
    session.on_change = lambda: cancel.set() if any(step.status == "done" for step in session.data.steps) else None
    result = recipes.run(session, design, [{"picture": source}] * 3, cancel)
    assert result["cancelled"]
    assert [row["status"] for row in result["rows"]] == ["done", "cancelled", "cancelled"]
    assert session.artifacts.data(result["rows"][0]["output_id"])


def test_named_design_rejects_undeclared_refs_and_project_image_defaults():
    with pytest.raises((ValueError, EngineError)):
        recipes.Recipe(version=2, name="Bad", steps=[{"tool": "transform", "params": {"image": "$input:missing"}}])
    with pytest.raises(ValueError, match="portable"):
        recipes.RecipeInput(kind="image", default="project-artifact")
