"""Desktop document safety: autosave is not a user Save, and replacement is conditional."""

import asyncio
import json
import threading

import pytest

from badshop.engine.errors import EngineError
from badshop.server import rpc
from badshop.session import project
from badshop.session.models import Part
from test_server_app import Client, Failed, HEAD, imported, run


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "out"))
    monkeypatch.delenv("BADSHOP_FAKE_PROVIDER", raising=False)
    return tmp_path


def test_event_context_distinguishes_reopening_and_retains_emission_ownership(env):
    async def body(app):
        c = Client(app)
        await imported(c)
        path = str(env / "context.badshop")
        await c.call("session.save_as", path=path)
        saved = await c.call("session.get")
        original = saved["context"]
        app._emit("message.delta", {"text": "old text"})
        reopened = await c.call("session.open", path=path)
        await c.event("message.delta")
        old_event = next(e for e in c.events if e["method"] == "message.delta")
        assert reopened["id"] == saved["id"]
        assert reopened["context"]["document_incarnation"] != original["document_incarnation"]
        assert old_event["context"]["document_incarnation"] == original["document_incarnation"]
        assert reopened["context"]["revision"] > original["revision"]
        app._emit("asset.progress", {"name": "asset", "done": 1, "total": 1})
        await c.event("asset.progress")
        global_event = next(e for e in c.events if e["method"] == "asset.progress")
        assert "context" not in global_event
        assert global_event["core_instance_id"] == original["core_instance_id"]
        assert global_event["event_seq"] > old_event["event_seq"]
    run(body)


def test_queued_command_cannot_mutate_a_replacement_document(env):
    async def body(app):
        c = Client(app)
        original = (await c.call('session.get'))['context']

        async def request(method, params):
            return json.loads(await app.dispatcher.handle(json.dumps({
                'jsonrpc': '2.0', 'id': method, 'method': method, 'params': params,
                'context': original,
            }), 'user'))

        await app._lock.acquire()
        try:
            replacement = asyncio.create_task(request('session.new', {'name': 'Replacement'}))
            await asyncio.sleep(0)
            queued = asyncio.create_task(request('session.set_approval_mode', {'mode': 'auto'}))
            await asyncio.sleep(0)
            assert not replacement.done() and not queued.done()
        finally:
            app._lock.release()
        assert 'result' in await replacement
        refused = await queued
        assert 'error' in refused, 'the queued mutation ran against the replacement document'
        assert refused['error']['code'] == -32002
        assert refused['error']['data']['outcome'] == 'not_started'
        current = await c.call('session.get')
        assert current['name'] == 'Replacement'
        assert current['approval_mode'] == 'ask_changes'
        assert current['context']['document_incarnation'] != original['document_incarnation']
        assert rpc.REQUEST_OWNERSHIP.get() is None
    run(body)


def test_old_incarnation_is_refused_even_when_saved_id_branch_and_revision_match(env):
    async def body(app):
        c = Client(app)
        await imported(c)
        path = str(env / 'reopen-context.badshop')
        await c.call('session.save_as', path=path)
        old = (await c.call('session.get'))['context']
        reopened = await c.call('session.open', path=path)
        old['revision'] = reopened['context']['revision']
        reply = json.loads(await app.dispatcher.handle(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'session.set_approval_mode',
            'params': {'mode': 'auto'}, 'context': old,
        }), 'user'))
        assert reply['error']['code'] == -32002
        assert (await c.call('session.get'))['approval_mode'] == 'ask_changes'
    run(body)


def test_recipe_stop_accepts_progress_but_rejects_another_document(env, monkeypatch):
    async def body(app):
        c = Client(app)
        image = await imported(c)
        context = (await c.call('session.get'))['context']
        entered = threading.Event()
        original = app.session.executor.run
        calls = 0

        def controlled(call, cancel=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                entered.set()
                assert cancel.wait(5), 'recipe Stop never reached the executing tool'
            return original(call, cancel=cancel)

        monkeypatch.setattr(app.session.executor, 'run', controlled)
        recipe = {'name': 'two effects', 'steps': [
            {'tool': 'filter', 'params': {'image': '$input', 'names': ['invert']}},
            {'tool': 'filter', 'params': {'image': '$step0', 'names': ['invert']}},
        ]}
        pending = asyncio.create_task(c.call('recipes.run', recipe=recipe, inputs=[image]))
        async def stop(owner):
            return json.loads(await app.dispatcher.handle(json.dumps({
                'jsonrpc': '2.0', 'id': 'stop', 'method': 'recipes.stop', 'context': owner,
            }), 'user'))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert app._document_revision > context['revision']
            wrong = {**context, 'document_incarnation': 'another-document'}
            assert (await stop(wrong))['error']['code'] == -32002
            assert not app._recipe_cancel.is_set()
            assert (await stop(context))['result'] == {'stopped': True}
            result = await pending
            assert result['cancelled']
            assert result['completed'] == ['s1']
            completed, cancelled = app.session.data.steps
            assert completed.status == 'done' and cancelled.status == 'error'
            output = app.session.artifacts.image(completed.outputs[0]).convert('RGB')
            source = app.session.artifacts.image(image).convert('RGB')
            assert output.getpixel((0, 0)) == tuple(255 - channel for channel in source.getpixel((0, 0)))
            reopened = project.open_project(project.autosave_path())
            assert reopened.artifacts.data(completed.outputs[0]) == app.session.artifacts.data(completed.outputs[0])
            assert app._recipe_cancel is None
        finally:
            if app._recipe_cancel is not None:
                app._recipe_cancel.set()
            await asyncio.gather(pending, return_exceptions=True)
    run(body)


def test_save_baseline_survives_autosave_and_failed_save(env, monkeypatch):
    async def body(app):
        c = Client(app)
        initial = await c.call("session.get")
        assert initial["unsaved_changes"] is False
        image = await imported(c)
        changed = await c.call("session.get")
        assert changed["document_revision"] > initial["document_revision"]
        assert changed["unsaved_changes"] is True
        assert not app._dirty  # autosave completed, but the user's document is still unsaved
        await c.call("session.save_as", path=str(env / "project.badshop"))
        saved = await c.call("session.get")
        assert saved["document_revision"] == changed["document_revision"]
        assert saved["unsaved_changes"] is False

        await c.call("tools.run", tool="cutout", params={"image": image, "box": HEAD, "no_ai": True})
        changed = await c.call("session.get")
        assert changed["document_revision"] > saved["document_revision"]
        assert changed["unsaved_changes"] is True
        with monkeypatch.context() as patch:
            def fail(*args):
                raise EngineError("disk full")
            patch.setattr(project, "save", fail)
            with pytest.raises(Failed, match="disk full"):
                await c.call("session.save_as", path=str(env / "failed.badshop"))
        assert await c.call("session.get") == changed
        await c.call("session.save")
        assert (await c.call("session.get"))["unsaved_changes"] is False

        # These are saved document state too, even without any pixel changes.
        await app._blocking(app.session.add_message, "user", [Part(type="text", text="keep this conversation")])
        message = await c.call("session.get")
        assert message["document_revision"] > changed["document_revision"]
        assert message["unsaved_changes"] is True
        await c.call("session.save")
        mode = await c.call("session.set_approval_mode", mode="ask_all")
        assert mode["unsaved_changes"] is True
        assert mode["document_revision"] > message["document_revision"]

    run(body)


@pytest.mark.parametrize("method", ["session.new", "session.open", "session.restore"])
def test_replacement_guard_preserves_current_document_and_approvals(env, method):
    async def body(app):
        c = Client(app)
        image = await imported(c)
        await c.call("session.save_as", path=str(env / "project.badshop"))
        saved = await c.call("session.get")
        cli = Client(app, "cli:external")
        pending = asyncio.create_task(cli.call("tools.run", tool="cutout",
                                              params={"image": image, "box": HEAD, "no_ai": True}))
        await c.waiting()
        before = await c.call("session.get")
        assert before["document_revision"] > saved["document_revision"]
        assert before["unsaved_changes"] is True  # the proposed approval is itself saved state
        autosave = project.autosave_path().read_bytes()
        params = {"path": str(env / "does-not-exist.badshop")} if method == "session.open" else {}
        try:
            # Guard before loading, missing-restore checks, or cancelling outstanding approvals.
            with pytest.raises(Failed, match="unsaved changes"):
                await c.call(method, **params, expected_revision=before["document_revision"])
            with pytest.raises(Failed, match="changed before"):
                await c.call(method, **params, expected_revision=before["document_revision"] - 1,
                             discard_unsaved=True)
            assert await c.call("session.get") == before
            assert project.autosave_path().read_bytes() == autosave
            assert not pending.done()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    run(body)


def test_a_stale_queued_switch_does_not_cancel_approvals(env, monkeypatch):
    async def body(app):
        c = Client(app)
        before = await c.call("session.get")
        cancellations = []
        monkeypatch.setattr(app, "_cancel_approvals", cancellations.append)
        async with app._lock:
            first = asyncio.create_task(c.call("session.new", expected_revision=before["document_revision"]))
            second = asyncio.create_task(c.call("session.new", expected_revision=before["document_revision"]))
            await asyncio.sleep(0)
        await first
        with pytest.raises(Failed, match="changed before"):
            await second
        assert cancellations == ["the user started a new session"]

    run(body)


def test_revision_is_checked_after_waiting_for_a_concurrent_mutation(env):
    async def body(app):
        c = Client(app)
        before = await c.call("session.get")
        async with app._lock:
            replacement = asyncio.create_task(c.call("session.new",
                expected_revision=before["document_revision"], discard_unsaved=True))
            await asyncio.sleep(0)  # replacement is now queued behind the mutation
            app.session.add_message("user", [Part(type="text", text="arrived while the dialog was open")])
        with pytest.raises(Failed, match="changed before"):
            await replacement
        assert (await c.call("session.get"))["id"] == before["id"]

    run(body)


def test_replacements_advance_revision_and_saved_state(env):
    async def first(app):
        c = Client(app)
        await imported(c)
        await c.call("session.save_as", path=str(env / "one.badshop"))

    run(first)

    async def second(app):
        c = Client(app)
        initial = await c.call("session.get")
        restored = await c.call("session.restore", expected_revision=initial["document_revision"])
        assert restored["unsaved_changes"] is True
        assert restored["document_revision"] > initial["document_revision"]
        old = app.session
        new = await c.call("session.new", expected_revision=restored["document_revision"], discard_unsaved=True)
        assert new["unsaved_changes"] is False
        assert new["document_revision"] > restored["document_revision"]
        old.add_message("user", [Part(type="text", text="late cleanup must not dirty the replacement")])
        assert await c.call("session.get") == new
        opened = await c.call("session.open", path=str(env / "one.badshop"),
                              expected_revision=new["document_revision"])
        assert opened["unsaved_changes"] is False
        assert opened["document_revision"] > new["document_revision"]
        await imported(c, name="another.png")
        legacy = await c.call("session.new")  # old headless clients keep their existing behavior
        assert legacy["unsaved_changes"] is False
        assert legacy["document_revision"] > opened["document_revision"]

    run(second)


def test_provider_and_step_changes_are_unsaved_document_state(env):
    async def body(app):
        c = Client(app)
        image = await imported(c)
        step = await c.call("tools.run", tool="cutout", params={"image": image, "box": HEAD, "no_ai": True})
        await c.call("session.save_as", path=str(env / "one.badshop"))
        await c.call("settings.set", values={"auto_replay": False})
        await c.call("providers.save", profile={"id": "local", "label": "Local",
            "model": "openai/local", "kind": "openai_compatible", "api_base": "http://localhost:1234/v1"})
        assert (await c.call("session.get"))["unsaved_changes"] is False  # profile config is separate
        changes = [
            ("providers.select", {"profile_id": "local"}),
            ("providers.delete", {"profile_id": "local"}),
            ("steps.edit", {"step_id": step["id"],
                            "params": {"image": image, "box": [100, 50, 300, 300], "no_ai": True}}),
            ("steps.replay_from", {"step_id": step["id"]}),
            ("steps.delete", {"step_id": step["id"]}),
        ]
        for method, params in changes:
            await c.call("session.save")
            saved = await c.call("session.get")
            await c.call(method, **params)
            changed = await c.call("session.get")
            assert changed["unsaved_changes"] is True, method
            assert changed["document_revision"] > saved["document_revision"], method

    run(body)


@pytest.mark.parametrize("params", [{"expected_revision": True}, {"expected_revision": -1},
                                    {"expected_revision": "0"}, {"discard_unsaved": "yes"}])
def test_replacement_tokens_are_strictly_validated(env, params):
    async def body(app):
        with pytest.raises(Failed) as error:
            await Client(app).call("session.new", **params)
        assert error.value.code == rpc.INVALID_PARAMS

    run(body)


@pytest.mark.parametrize("method", ["session.save", "session.save_as"])
def test_save_checks_revision_after_queued_replacement_before_writing(env, method):
    async def body(app):
        c = Client(app)
        await imported(c)
        path = env / "one.badshop"
        await c.call("session.save_as", path=str(path))
        original_bytes = path.read_bytes()
        before = await c.call("session.get")
        params = {"path": str(path)} if method == "session.save_as" else {}
        async with app._lock:
            replacement = asyncio.create_task(c.call("session.new"))
            queued_save = asyncio.create_task(c.call(method, **params,
                expected_revision=before["document_revision"]))
            await asyncio.sleep(0)
        new = await replacement
        with pytest.raises(Failed, match="changed before"):
            await queued_save
        assert path.read_bytes() == original_bytes  # never overwrite it with the replacement document
        assert await c.call("session.get") == new

        # A matching token saves normally; omitting the token retains the headless API.
        await c.call("session.save_as", path=str(path), expected_revision=new["document_revision"])
        assert await c.call("session.save") == {"path": str(path)}

    run(body)
