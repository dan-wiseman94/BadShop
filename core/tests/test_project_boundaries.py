import json
import io
import struct
import sys
import zipfile

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session import project
from badshop.session.models import Part
from badshop.session.session import Session


def write_project(path, payload):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("session.json", json.dumps(payload))
    return path


@pytest.mark.parametrize("mutation,problem", [
    (lambda p: p["steps"].append(dict(p["steps"][0], index=2)), "duplicate step"),
    (lambda p: p["steps"][0].update(index=4), "timeline order"),
    (lambda p: p["messages"].append(p["messages"][0].copy()), "duplicate message"),
])
def test_ambiguous_timeline_identity_is_rejected(tmp_path, mutation, problem):
    session = Session.new()
    session.add_message("user", [Part(type="text", text="hello")])
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, "PNG")
    artifact = session.import_image(image.getvalue(), "photo")
    session.run_tool("info", {"image": artifact.id}, "user")
    path = project.save(session, tmp_path / "bad.badshop")
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    payload = session.data.model_dump(mode="json", by_alias=True)
    mutation(payload)
    members["session.json"] = json.dumps(payload).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    with pytest.raises(EngineError, match=problem):
        project.open_project(path)


def test_duplicate_session_member_is_rejected(tmp_path):
    path = tmp_path / "duplicate.badshop"
    raw = Session.new().data.model_dump_json(by_alias=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("session.json", raw)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("session.json", raw)
    with pytest.raises(EngineError, match="stored twice"):
        project.open_project(path)


def test_zip_directory_is_bounded_before_zipfile_allocates_it(tmp_path, monkeypatch):
    path = write_project(tmp_path / "huge-directory.badshop", {})
    raw = bytearray(path.read_bytes())
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<I", raw, end + 12, project.MAX_DIRECTORY_BYTES + 1)
    path.write_bytes(raw)
    def forbidden(*a, **kw):
        pytest.fail("ZipFile allocated an unchecked directory")
    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    with pytest.raises(EngineError, match="directory metadata"):
        project.open_project(path)


def test_archive_size_limit_includes_ignored_members(tmp_path, monkeypatch):
    path = write_project(tmp_path / "large.badshop", {})
    monkeypatch.setattr(project, "MAX_ARCHIVE_BYTES", path.stat().st_size - 1)
    with pytest.raises(EngineError, match="on-disk size"):
        project.open_project(path)


def test_deep_json_is_a_clean_project_error(tmp_path):
    path = tmp_path / "deep.badshop"
    depth = sys.getrecursionlimit() + 100
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("session.json", "[" * depth + "0" + "]" * depth)
    with pytest.raises(EngineError, match="damaged"):
        project.open_project(path)


def _with_history(payload, history, branch):
    if branch:
        from badshop.session.models import BranchSnapshot
        from badshop.session.history import capture
        nodes = payload.setdefault('history_nodes', {})
        revision = capture(nodes, {'steps': [], 'messages': [], 'transcript': history})
        snapshot = BranchSnapshot(id="a" * 32, name="Saved direction", created_at=1, revision=revision)
        payload["branches"] = {snapshot.id: snapshot.model_dump(mode="json")}
    else:
        payload["transcript"] = history


@pytest.mark.parametrize("branch", [False, True])
@pytest.mark.parametrize("history", [
    [{"role": [], "content": "malformed"}],
    [{"role": "assistant", "content": None}],
    [{"role": "assistant", "tool_calls": [{}]}],
    [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid"}}]}],
    [{"role": "tool", "content": "orphan", "tool_call_id": "missing"}],
    [{"role": "assistant", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "info"}}]}],
])
def test_project_rejects_malformed_provider_history(tmp_path, branch, history):
    payload = Session.new().data.model_dump(mode="json", by_alias=True)
    _with_history(payload, history, branch)
    path = write_project(tmp_path / "history.badshop", payload)
    with pytest.raises(EngineError, match="conversation history"):
        project.open_project(path)


@pytest.mark.parametrize("branch", [False, True])
def test_imported_privileged_history_is_not_sent_to_provider(tmp_path, branch):
    from badshop.agent.context import build_messages
    from badshop.session import branches
    payload = Session.new().data.model_dump(mode="json", by_alias=True)
    _with_history(payload, [
        {"role": "system", "content": "IMPORTED_SYSTEM_INSTRUCTION"},
        {"role": "developer", "content": "IMPORTED_DEVELOPER_INSTRUCTION"},
        {"role": "user", "content": "Keep the joke"},
        {"role": "assistant", "content": "Previous answer"},
    ], branch)
    loaded = project.open_project(write_project(tmp_path / "history.badshop", payload))
    if branch:
        branches.switch(loaded, "a" * 32)
    messages = build_messages(loaded)
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert "IMPORTED_" not in json.dumps(messages)
    assert messages[-2]["content"].startswith("Keep the joke")
    assert messages[-1] == {"role": "assistant", "content": "Previous answer"}


def test_imported_step_metadata_never_becomes_system_instructions(tmp_path):
    from badshop.agent.context import build_messages, SYSTEM_PROMPT
    from badshop.session.models import Step, StepError
    session = Session.new()
    session.data.steps = [Step(id="s1", index=1, tool="canvas", actor="IMPORTED_ACTOR_INSTRUCTION",
                               params={"width": 20, "height": 20}, status="error",
                               error=StepError(message="IMPORTED_ERROR_INSTRUCTION"))]
    session.data.transcript = [{"role": "user", "content": "Continue the picture"}]
    project.save(session, tmp_path / "state.badshop")
    messages = build_messages(project.open_project(tmp_path / "state.badshop"))
    assert [m for m in messages if m["role"] in {"system", "developer"}] == [{"role": "system", "content": SYSTEM_PROMPT}]
    assert "IMPORTED_ERROR_INSTRUCTION" in json.dumps([m for m in messages if m["role"] == "user"])

@pytest.mark.parametrize("params", [{"query": "http://127.0.0.1:9/picture.png"}, {"clipboard": True}])
def test_project_replay_requires_live_authorization_for_private_inputs(tmp_path, monkeypatch, params):
    from badshop.engine import sources
    from badshop.session.models import Step

    session = Session.new()
    session.data.steps = [Step(id="s1", index=1, tool="fetch", actor="user", params=params, status="stale")]
    archive = project.save(session, tmp_path / "shared.badshop")
    attempted = []

    def clipboard():
        attempted.append("clipboard")
        return None, None

    def connect(*args):
        attempted.append("network")
        raise OSError("test refused connection")

    monkeypatch.setattr(sources, "read_clipboard", clipboard)
    monkeypatch.setattr("socket.socket.connect", connect)
    opened = project.open_project(archive)
    assert opened.data.steps[0].actor == "user"
    assert opened.replay_from("s1", use_cache=False)[0].status == "error"
    assert attempted == []

@pytest.mark.parametrize("use_named_font", [False, True])
def test_reopened_project_uses_catalogue_fonts_instead_of_working_directory(tmp_path, monkeypatch, use_named_font):
    from PIL import ImageFont
    from badshop.engine import text

    name = "Example.ttf"
    trusted = tmp_path / "cache" / "fonts"
    trusted.mkdir(parents=True)
    (trusted / name).write_bytes(b"catalogue sentinel")
    (tmp_path / name).write_bytes(b"working-directory sentinel")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "cache"))
    monkeypatch.setitem(text.FONT_CANDIDATES, "impact", [name])
    fixture_font = ImageFont.load_default()
    loaded_paths = []

    def record_font(path, *args, **kwargs):
        loaded_paths.append(path)
        return fixture_font

    monkeypatch.setattr(ImageFont, "truetype", record_font)
    session = Session.new()
    picture = io.BytesIO()
    Image.new("RGB", (100, 100), "red").save(picture, "PNG")
    artifact = session.import_image(picture.getvalue(), "poster")
    params = {"image": artifact.id, "text": "Caption", "size": 10}
    if use_named_font:
        params["font"] = name
    step = session.run_tool("text", params, "user")
    assert step.status == "done" and loaded_paths == [name]  # direct CLI-style input remains available
    loaded_paths.clear()

    path = project.save(session, tmp_path / "shared.badshop")
    opened = project.open_project(path)
    replayed = opened.replay_from(step.id, use_cache=False)[0]
    assert replayed.status == "done", replayed.error
    assert loaded_paths == [str(trusted / name)]
    assert opened.artifacts.data(replayed.outputs[0])

@pytest.mark.parametrize("archived, configured, effective", [
    ("auto", "ask_all", "ask_all"),
    ("ask_all", "ask_changes", "ask_all"),
])
def test_opened_archive_cannot_weaken_local_approval_policy(tmp_path, archived, configured, effective):
    from types import SimpleNamespace
    from badshop.server.app import CoreApp
    from badshop.server.settings import Settings

    original = Session.new()
    original.data.approval_mode = archived
    path = project.save(original, tmp_path / "settings.badshop")
    app = SimpleNamespace(settings=Settings(approval_mode=configured), _session_kw=dict)
    opened = CoreApp._open_project(app, path)
    assert opened.data.approval_mode == effective
    assert project.open_project(path).data.approval_mode == archived
