import asyncio
import json
import sqlite3
import uuid
import threading

from badshop.engine.errors import EngineError
from badshop.session import project, recovery
from badshop.session.session import Session
from test_server_app import Client, imported, run, script
from test_server_app import env as env


def test_running_step_is_visible_and_recoverable_before_worker_finishes(env, monkeypatch):
    async def body(app):
        client = Client(app)
        image = await imported(client)
        entered, release = threading.Event(), threading.Event()
        original = app.session.executor.run
        def controlled(call, cancel=None):
            entered.set()
            assert release.wait(10)
            return original(call, cancel)
        monkeypatch.setattr(app.session.executor, 'run', controlled)
        task = asyncio.create_task(client.call('tools.run', tool='filter', params={'image': image, 'names': ['invert']}))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            await asyncio.sleep(0.05)
            assert 'step.started' in client.methods()
            assert 'step.finished' not in client.methods()
            recovered = await asyncio.to_thread(recovery.load, project.autosave_path())
            assert len(recovered.data.steps) == 1
            assert recovered.data.steps[0].status == 'error'  # interrupted work never resumes silently
        finally:
            release.set()
            await task
        assert app.session.data.steps[0].status == 'done'
    run(body)


def test_terminal_event_waits_for_commit_and_accepts_the_next_owned_edit(env, monkeypatch):
    async def body(app):
        client = Client(app)
        await client.call('settings.set', values={'fake_provider_script': script(env, [{'text': 'Finished.'}])})
        entered, release = threading.Event(), threading.Event()
        original = project.autosave
        def controlled(session):
            if app._run and app._run.outcome:
                entered.set()
                assert release.wait(10)
            return original(session)
        monkeypatch.setattr(project, 'autosave', controlled)
        task = asyncio.create_task(client.call('chat.send', text='Hello'))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert 'turn.finished' not in client.methods()
        finally:
            release.set()
            await task
        await client.event('turn.finished')
        event = next(item for item in client.events if item['method'] == 'turn.finished')
        restored = recovery.load(project.autosave_path())
        try:
            assert restored.data.messages[-1].content[0].text == 'Finished.'
        finally:
            restored.artifacts.close()
        frame = json.dumps({'jsonrpc': '2.0', 'id': 90, 'method': 'tools.run',
            'params': {'tool': 'canvas', 'params': {'width': 8, 'height': 8, 'background': 'red'}},
            'context': event['context'], 'operation_id': uuid.uuid4().hex})
        reply = json.loads(await app.dispatcher.handle(frame, 'user'))
        assert reply['result']['status'] == 'done', reply
        usage = (await client.call('session.get'))['provider_usage']
        assert {'requested_model', 'actual_model', 'input_tokens', 'output_tokens', 'omitted_turns'} <= usage.keys()
    run(body)


def test_retry_returns_receipt_without_repeating_pixels_or_steps(env):
    async def body(app):
        client = Client(app)
        image = await imported(client)
        operation_id = uuid.uuid4().hex
        frame = json.dumps({'jsonrpc': '2.0', 'id': 20, 'method': 'tools.run',
                            'params': {'tool': 'filter', 'params': {'image': image, 'names': ['invert']}},
                            'context': app._document_context(), 'operation_id': operation_id})
        first = json.loads(await app.dispatcher.handle(frame, 'user'))
        assert 'result' in first, first
        output = first['result']['outputs'][0]
        pixels = app.session.artifacts.data(output)
        second = json.loads(await app.dispatcher.handle(frame, 'user'))
        assert second == first
        assert len(app.session.data.steps) == 1
        restored = recovery.load(project.autosave_path())
        assert restored.data.steps[0].operation_id == operation_id
        assert restored.artifacts.data(output) == pixels
        receipt = await client.call('operations.get', operation_id=operation_id)
        assert receipt['status'] == 'committed' and receipt['result'] == first['result']
        assert receipt['steps'][0]['invocation_id'] == restored.data.steps[0].invocation_id
        changed = json.loads(frame)
        changed['params']['params']['names'] = ['sepia']
        rejected = json.loads(await app.dispatcher.handle(json.dumps(changed), 'user'))
        assert 'reused' in rejected['error']['message']
        assert len(app.session.data.steps) == 1
    run(body)


def test_failed_commit_does_not_publish_finished_or_repeat_pending_operation(env, monkeypatch):
    async def body(app):
        client = Client(app)
        image = await imported(client)
        operation_id = uuid.uuid4().hex
        original = project.autosave
        def fail(session):
            raise EngineError('injected disk failure')
        monkeypatch.setattr(project, 'autosave', fail)
        frame = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools.run',
                            'params': {'tool': 'filter', 'params': {'image': image, 'names': ['invert']}},
                            'operation_id': operation_id})
        reply = json.loads(await app.dispatcher.handle(frame, 'user'))
        assert 'injected disk failure' in reply['error']['message']
        await asyncio.sleep(0)
        assert 'step.finished' not in client.methods()
        assert recovery.operation(project.autosave_path(), operation_id)['status'] == 'pending'
        again = json.loads(await app.dispatcher.handle(frame, 'user'))
        assert again['error']['data']['outcome'] == 'pending'
        assert len(app.session.data.steps) == 1
        monkeypatch.setattr(project, 'autosave', original)
    run(body)


def test_storage_upgrade_keeps_readable_version_one_rollback(tmp_path):
    path = tmp_path / 'recovery.sqlite'
    session = Session.new('before migration')
    recovery.save(session, path)
    with sqlite3.connect(path) as connection:
        connection.execute('DROP TABLE operations')
        connection.execute('PRAGMA user_version=1')
    session.data.name = 'after migration'
    recovery.save(session, path)
    backup = tmp_path / 'recovery.pre-v2.sqlite'
    assert recovery.load(backup).data.name == 'before migration'
    assert recovery.load(path).data.name == 'after migration'
    before = backup.read_bytes()
    recovery.save(session, path)
    assert backup.read_bytes() == before


def test_inspection_preserves_corrupt_evidence_and_reports_healthy_store(tmp_path):
    good = tmp_path / 'good.sqlite'
    bad = tmp_path / 'bad.sqlite'
    recovery.save(Session.new('healthy'), good)
    bad.write_bytes(b'damaged database evidence')
    before = {path.name: path.read_bytes() for path in (good, bad)}
    reports = {row['file']: row for row in recovery.inspect(tmp_path)}
    assert reports['good.sqlite']['ok'] and not reports['bad.sqlite']['ok']
    assert {path.name: path.read_bytes() for path in (good, bad)} == before


def test_storage_upgrade_preserves_existing_backup_and_current_version_one(tmp_path):
    path = tmp_path / 'recovery.sqlite'
    backup = tmp_path / 'recovery.pre-v2.sqlite'
    backup.write_bytes(b'older damaged evidence')
    session = Session.new('current version one')
    recovery.save(session, path)
    with sqlite3.connect(path) as connection:
        connection.execute('DROP TABLE operations')
        connection.execute('PRAGMA user_version=1')
    session.data.name = 'upgraded'
    recovery.save(session, path)
    assert backup.read_bytes() == b'older damaged evidence'
    assert recovery.load(tmp_path / 'recovery.pre-v2.1.sqlite').data.name == 'current version one'
    assert recovery.load(path).data.name == 'upgraded'


def test_receipt_reply_eviction_retains_identity_and_committed_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'RECEIPT_RESULT_BUDGET', 1000)
    path = tmp_path / 'recovery.sqlite'
    session = Session.new()
    receipt = {'id': uuid.uuid4().hex, 'fingerprint': 'a' * 64, 'method': 'tools.run',
               'document_id': session.data.id, 'status': 'committed', 'created_at': 1,
               'result': {'large': 'x' * 2000}}
    recovery.save(session, path, operation=receipt)
    restored = recovery.operation(path, receipt['id'])
    assert restored == {**receipt, 'result': None}
    assert recovery.record_intent(path, {**receipt, 'status': 'pending'}) == restored
