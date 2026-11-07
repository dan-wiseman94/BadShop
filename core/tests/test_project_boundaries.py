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
