import io

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session import branches, project
from badshop.session.session import Session
from test_server_app import Client, Failed, imported as server_imported, run
from test_server_app import env as env


def imported(session):
    data = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(data, "PNG")
    with branches.manual_edit(session, "import image"):
        return session.import_image(data.getvalue(), "source")


def test_history_restores_pixels_and_materials_after_save_reopen(tmp_path):
    session = Session.new()
    source = imported(session)
    with branches.manual_edit(session, "filter"):
        first = session.run_tool("filter", {"image": source.id, "names": ["invert"]}, "user")
    with branches.manual_edit(session, "transform"):
        last = session.run_tool("transform", {"image": first.outputs[0], "width": 20}, "user")
    final = session.artifacts.data(last.outputs[0])
    session.output_dir = tmp_path
    exported = session.export(last.outputs[0], "external")
    branches.manual_restore(session)
    assert len(session.data.steps) == 1
    path = project.save(session, tmp_path / "history.badshop")
    session = project.open_project(path)
    branches.manual_restore(session, redo=True)
    assert session.artifacts.data(session.data.steps[-1].outputs[0]) == final
    for _ in range(3):
        branches.manual_restore(session)
    assert session.data.steps == []
    assert session.visible_artifact_ids() == set()
    assert exported.read_bytes() == final
    branches.manual_restore(session, redo=True)
    assert source.id in session.visible_artifact_ids()


def test_new_edit_clears_redo_and_invalid_edit_keeps_history():
    session = Session.new()
    source = imported(session)
    with branches.manual_edit(session, "filter"):
        session.run_tool("filter", {"image": source.id, "names": ["invert"]}, "user")
    branches.manual_restore(session)
    before = session.data.model_dump_json()
    with pytest.raises(EngineError):
        with branches.manual_edit(session, "bad edit"):
            session.edit("s999", {})
    assert session.data.model_dump_json() == before
    with branches.manual_edit(session, "transform"):
        session.run_tool("transform", {"image": source.id, "width": 10}, "user")
    assert session.data.manual_redo == []
    with pytest.raises(EngineError, match="no manual change to redo"):
        branches.manual_restore(session, redo=True)


def test_manual_edit_and_dependent_replay_form_one_undo_entry():
    session = Session.new()
    source = imported(session)
    with branches.manual_edit(session, "filter"):
        first = session.run_tool("filter", {"image": source.id, "names": ["invert"]}, "user")
    with branches.manual_edit(session, "transform"):
        session.run_tool("transform", {"image": first.outputs[0], "width": 20}, "user")
    old = [step.model_dump() for step in session.data.steps]
    with branches.manual_edit(session, "edit step"):
        session.edit(first.id, {**first.params, "names": ["grayscale"]})
    session.replay_from(first.id)
    revised = [step.model_dump() for step in session.data.steps]
    branches.manual_restore(session)
    assert [step.model_dump() for step in session.data.steps] == old
    branches.manual_restore(session, redo=True)
    assert [step.model_dump() for step in session.data.steps] == revised


def test_history_is_bounded_and_direction_changes_clear_it():
    session = Session.new()
    imported(session)
    for seed in range(35):
        with branches.manual_edit(session, "creative settings"):
            session.data.creative.seed = seed + 2
    assert len(session.data.manual_undo) == 30
    branches.create(session, "Another direction")
    assert not session.data.manual_undo
    assert not session.data.manual_redo


def test_pending_step_failure_does_not_erase_history_or_suppress_error():
    session = Session.new()
    source = imported(session)
    session.propose("filter", {"image": source.id, "names": ["invert"]}, "user")
    before = session.data.model_dump_json()
    with pytest.raises(EngineError, match="no such step"):
        with branches.manual_edit(session, "bad edit"):
            session.edit("s999", {})
    assert session.data.model_dump_json() == before
    with pytest.raises(EngineError, match="finish or reject"):
        branches.manual_restore(session)


@pytest.mark.usefixtures("env")
def test_history_rpc_refuses_stale_revision_and_agent_access():
    async def body(app):
        client = Client(app)
        await server_imported(client)
        before = await client.call("session.get")
        await client.call("creative.set", values={"seed": 5})
        with pytest.raises(Failed, match="changed"):
            await client.call("history.undo", expected_revision=before["document_revision"])
        current = await client.call("session.get")
        assert current["creative"]["seed"] == 5
        with pytest.raises(Failed):
            await Client(app, "cli:codex").call("history.undo")
        restored = await client.call("history.undo", expected_revision=current["document_revision"])
        assert restored["creative"]["seed"] == before["creative"]["seed"]
    run(body)
