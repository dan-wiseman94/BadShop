"""Open populated archives produced by historical versions of the project writer."""

import hashlib
import io
import json
import zipfile

import pytest
from PIL import Image

from badshop.session import branches, project
from badshop.session.models import SCHEMA
from conftest import FIXTURES

SOURCE = "dd0b870de12961646c0def2af0b002554ed098ff4b03d6737170e7fbd2fb4b04"
INVERT = "c25f5c2c00100f9e4570ff524ec27ed7d794f7f3ff3874ff5dfa8d0de6e280df"
SEPIA = "f4bfd912ee0b3670c44b59898331b3bef8ccccde80019bc207cce733e502359e"
GRAYSCALE = "11f57f6de672e94aecae5e35902828235cfbd6a74f2b861d741b93b0ab1be085"


def pixels(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.size, image.convert("RGBA").tobytes()


def assert_timeline(session, effect, output, step_id):
    first, second = session.data.steps
    assert [(s.id, s.tool, s.status) for s in (first, second)] == [
        ("s1", "filter", "done"), (step_id, "filter", "done"),
    ]
    assert (first.params, first.outputs) == ({"image": SOURCE, "names": ["invert"]}, [INVERT])
    assert (second.params, second.outputs) == ({"image": INVERT, "names": [effect]}, [output])
    user, assistant = session.data.messages
    assert user.content[1].artifact_id == SOURCE
    assert assistant.step_ids == [first.id]


@pytest.mark.parametrize("name, schema", [("schema-1", 1), ("desktop-v0.1.0", 2)])
def test_historical_project_keeps_references_bytes_and_replay(name, schema, tmp_path):
    fixture = FIXTURES / "projects" / f"{name}.badshop"
    with zipfile.ZipFile(fixture) as archive:
        assert json.loads(archive.read("session.json"))["schema"] == schema
    expected = {SOURCE, INVERT, SEPIA} | ({GRAYSCALE} if schema == 2 else set())

    opened = project.open_project(fixture, output_dir=tmp_path)
    assert opened.data.schema_ == SCHEMA
    assert opened.referenced_ids() == expected
    saved_copy = project.save(opened, tmp_path / "copy.badshop")
    reopened = project.open_project(saved_copy, output_dir=tmp_path)
    assert reopened.data == opened.data
    assert reopened.referenced_ids() == expected
    for artifact_id in expected:
        original = opened.artifacts.data(artifact_id)
        assert hashlib.sha256(original).hexdigest() == artifact_id
        assert reopened.artifacts.data(artifact_id) == original

    if schema == 2:
        ids = {branch.name: branch.id for branch in reopened.data.branches.values()}
        assert set(ids) == {"Original", "Alternate"}
        assert reopened.data.active_branch_id == ids["Alternate"]
        assert_timeline(reopened, "grayscale", GRAYSCALE, "s3")
        branches.switch(reopened, ids["Original"])
    assert_timeline(reopened, "sepia", SEPIA, "s2")
    replay = reopened.replay_from("s1", use_cache=False)
    assert [step.status for step in replay] == ["done", "done"]
    for step, historical_id in zip(replay, (INVERT, SEPIA), strict=True):
        assert pixels(reopened.artifacts.data(step.outputs[0])) == pixels(opened.artifacts.data(historical_id))
    assert replay[1].params["image"] == replay[0].outputs[0]
