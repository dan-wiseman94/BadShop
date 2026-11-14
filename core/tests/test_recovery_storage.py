import sqlite3
import subprocess
import sys

import pytest

from badshop.engine.errors import EngineError
from badshop.session import project, recovery
from badshop.session.session import Session
from test_project import meme, snapshot


def test_legacy_recovery_migrates_without_overwriting_backup(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    source = meme(tmp_path)
    legacy = project.autosave_path().with_suffix('.badshop')
    project.save(source, legacy)
    original = legacy.read_bytes()
    claimed = project.claim_autosave()
    assert claimed.name == 'previous.badshop'
    restored = project.open_project(claimed, output_dir=tmp_path)
    project.autosave(restored)
    assert claimed.read_bytes() == original
    recovered = project.open_project(project.autosave_path(), output_dir=tmp_path)
    assert snapshot(recovered) == snapshot(restored)
    for aid in recovered.artifacts.ids():
        assert recovered.artifacts.data(aid) == source.artifacts.data(aid)
    exported = project.save(recovered, tmp_path / 'portable.badshop')
    assert snapshot(project.open_project(exported, output_dir=tmp_path)) == snapshot(recovered)


def test_failed_metadata_commit_preserves_previous_document(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    source = Session.new('before', output_dir=tmp_path)
    project.autosave(source)
    old_put = recovery.Nodes.put
    def fail(self, value):
        old_put(self, 'uncommitted node')
        raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(recovery.Nodes, 'put', fail)
    source.data.name = 'after'
    with pytest.raises(EngineError, match='commit recovery'):
        project.autosave(source)
    assert project.open_project(project.autosave_path()).data.name == 'before'


def test_failed_first_commit_is_not_offered_over_previous_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    project.autosave(Session.new('kept'))
    previous = project.claim_autosave()
    before = previous.read_bytes()
    def fail(self, value):
        raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(recovery.Nodes, 'put', fail)
    with pytest.raises(EngineError):
        project.autosave(Session.new('failed'))
    assert not project.autosave_path().exists()
    assert project.claim_autosave() == previous
    assert previous.read_bytes() == before


def test_shared_metadata_membership_grows_linearly(tmp_path):
    connection = sqlite3.connect(tmp_path / 'metadata.sqlite')
    try:
        recovery._version(connection, create=True)
        for count in range(1, 201):
            recovery.Nodes(connection).put(list(range(count)))
        count = connection.execute('SELECT count(*) FROM nodes').fetchone()[0]
        # Full lists per revision would retain 20,100 memberships. Chunked nodes
        # keep unchanged prefixes and store only a tail plus logarithmic parents.
        assert count < 700
    finally:
        connection.close()


def test_collection_preserves_previous_recovery_and_refuses_corrupt_roots(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    source = meme(tmp_path)
    project.autosave(source)
    previous = project.claim_autosave()
    project.autosave(Session.new('fresh'))
    folder = previous.parent
    before = set((folder / 'blobs').iterdir())
    recovery.collect(folder, grace_seconds=0)
    assert set((folder / 'blobs').iterdir()) == before
    # An unreadable root must not make every historical image look unreachable.
    previous.write_bytes(b'corruption')
    recovery.collect(folder, grace_seconds=0)
    assert set((folder / 'blobs').iterdir()) == before
    # Only after the retained recovery is explicitly removed may its bytes go.
    previous.unlink()
    recovery.collect(folder, grace_seconds=0)
    assert list((folder / 'blobs').iterdir()) == []


def test_claim_recovers_hot_journal_before_moving_database(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    project.autosave(Session.new('committed'))
    path = project.autosave_path()
    script = '''
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA cache_size=1')
connection.execute('BEGIN IMMEDIATE')
connection.execute('UPDATE nodes SET body=randomblob(100000)')
os._exit(19)
'''
    result = subprocess.run([sys.executable, '-c', script, str(path)], check=False)
    assert result.returncode == 19
    assert path.with_name(path.name + '-journal').exists()
    previous = project.claim_autosave()
    assert previous is not None
    assert project.open_project(previous).data.name == 'committed'
    assert not path.with_name(path.name + '-journal').exists()


def test_commit_refuses_corrupted_existing_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    source = Session.new('kept')
    project.autosave(source)
    connection = sqlite3.connect(project.autosave_path())
    try:
        connection.execute("UPDATE nodes SET body=x'00'")
        connection.commit()
    finally:
        connection.close()
    before = project.autosave_path().read_bytes()
    with pytest.raises(EngineError, match='integrity'):
        project.autosave(source)
    assert project.autosave_path().read_bytes() == before


def test_corrupt_recovery_is_preserved_without_blocking_fresh_work(tmp_path, monkeypatch):
    monkeypatch.setenv('BADSHOP_DATA_DIR', str(tmp_path / 'data'))
    project.autosave(Session.new('old'))
    project.autosave_path().write_bytes(b'corruption evidence')
    offered = project.claim_autosave()
    assert offered.read_bytes() == b'corruption evidence'
    assert project.claim_autosave() == offered
    with pytest.raises(EngineError, match='damaged'):
        project.open_project(offered)
    project.autosave(Session.new('fresh'))
    assert project.open_project(project.autosave_path()).data.name == 'fresh'
    assert offered.read_bytes() == b'corruption evidence'
