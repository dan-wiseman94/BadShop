"""Persisted history sharing, legacy rollback copies, and corrupt-root rejection."""

import hashlib
import json
import shutil

import pytest

from badshop.engine.errors import EngineError
from badshop.session import branches, history, project
from badshop.session.session import Session
from badshop.session.models import Part
from conftest import FIXTURES


def test_legacy_overwrite_preserves_verified_bytes_and_existing_backup(tmp_path):
    source = FIXTURES / 'projects' / 'desktop-v0.1.0.badshop'
    path = tmp_path / 'project.badshop'
    shutil.copyfile(source, path)
    occupied = tmp_path / 'project.pre-v5.badshop'
    occupied.write_bytes(b'never replace this backup')
    session = project.open_project(path)
    project.save(session, path)
    backup = tmp_path / 'project.pre-v5-1.badshop'
    assert backup.read_bytes() == source.read_bytes()
    assert occupied.read_bytes() == b'never replace this backup'
    restored = project.open_project(path)
    assert restored.data == session.data
    for aid in session.referenced_ids():
        assert restored.artifacts.data(aid) == session.artifacts.data(aid)
    assert not list(tmp_path.glob('*.part'))


def test_failed_backup_publication_leaves_legacy_project_intact(tmp_path, monkeypatch):
    source = FIXTURES / 'projects' / 'schema-1.badshop'
    path = tmp_path / 'project.badshop'
    shutil.copyfile(source, path)
    session = project.open_project(path)

    publication = 'link' if project.os.name != 'nt' else 'rename'
    original = getattr(project.os, publication)

    def fail(source, destination, *args, **kwargs):
        if '.pre-v5' in str(destination):
            raise OSError('backup disk failure')
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(project.os, publication, fail)
    with pytest.raises(EngineError, match='backup disk failure'):
        project.save(session, path)
    assert path.read_bytes() == source.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['project.badshop']


def test_history_prefixes_share_records_and_activation_is_independent(tmp_path):
    session = Session.new()
    for index in range(100):
        session.add_message('user', [Part(type='text', text=f'message {index}')])
    branches.create(session, 'First')
    first = session.data.active_branch_id
    count = len(session.data.history_nodes)
    session.add_message('user', [Part(type='text', text='another message')])
    branches.create(session, 'Second')
    second = session.data.active_branch_id
    assert len(session.data.history_nodes) - count < 10
    session.data.messages[0].content[0].text = 'changed only here'
    branches.switch(session, first)
    assert session.data.messages[0].content[0].text == 'message 0'
    branches.switch(session, second)
    assert session.data.messages[0].content[0].text == 'changed only here'
    restored = project.open_project(project.save(session, tmp_path / 'shared.badshop'))
    branches.switch(restored, first)
    assert restored.data.messages[0].content[0].text == 'message 0'


def test_corrupt_history_cannot_be_materialized_or_collected():
    nodes = {}
    root = history.capture(nodes, dict(steps=[], messages=[], transcript=[]))
    nodes[root] += ' '
    before = dict(nodes)
    with pytest.raises(EngineError, match='integrity'):
        history.materialize(nodes, root)
    with pytest.raises(EngineError, match='integrity'):
        history.collect(nodes, [root])
    assert nodes == before


def test_valid_hash_with_wrong_node_kind_is_rejected():
    raw = json.dumps(['record', {'steps': [], 'messages': [], 'transcript': []}])
    root = hashlib.sha256(raw.encode('ascii')).hexdigest()
    with pytest.raises(EngineError, match='record type'):
        history.materialize({root: raw}, root)


def test_shared_membership_cannot_hide_an_oversized_expanded_revision(monkeypatch):
    nodes = {}
    record = {'content': 'x' * 1024}
    root = history.capture(nodes, dict(steps=[], messages=[record] * 32, transcript=[]))
    assert sum(len(raw) for raw in nodes.values()) < 4096
    before = dict(nodes)
    monkeypatch.setattr(history, 'MAX_EXPANDED_BYTES', 8192)
    with pytest.raises(EngineError, match='revision is too large'):
        history.collect(nodes, [root])
    assert nodes == before


def test_shared_subtree_cannot_hide_excessive_depth():
    nodes = {}
    record = history._node(nodes, 'record', {})
    shallow = history._node(nodes, 'list', [record])
    deep = shallow
    for _ in range(31):
        deep = history._node(nodes, 'concat', [deep])
    root = history._node(nodes, 'state', dict(steps=shallow, messages=deep, transcript=shallow))
    before = dict(nodes)
    for read in (lambda: history.collect(nodes, [root]), lambda: history.materialize(nodes, root)):
        with pytest.raises(EngineError, match='too deeply nested'):
            read()
    assert nodes == before
