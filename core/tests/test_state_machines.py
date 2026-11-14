"""Reachable state-machine failures; each test names a repair in docs/state-machines.md."""

import asyncio
import base64
import json
import threading

import pytest

from badshop.agent.approval import ApprovalGate
from badshop.agent.fake import ScriptedProvider
from badshop.agent.loop import TurnConfig, run_turn
from badshop.agent.provider import ProviderError, Reply
from badshop.engine.errors import EngineError
from badshop.server import app as server_app
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.session import project
from badshop.session.execution import InProcessExecutor
from badshop.session.session import Session
from test_server_app import Client, env as env
from conftest import FIXTURES

IMAGE = (FIXTURES / "lincoln.png").read_bytes()


def make_app(**settings):
    return CoreApp(Settings(**settings), executor_factory=lambda **_: InProcessExecutor())


def test_autosave_failure_remains_retryable_without_another_edit(env, monkeypatch):
    async def scenario():
        app = make_app()
        real_save, attempts = project.autosave, []

        def save(session):
            attempts.append(session.data.id)
            if len(attempts) == 1:
                raise EngineError("temporary full disk")
            real_save(session)

        monkeypatch.setattr(project, "autosave", save)
        try:
            await app._blocking(app.session.import_image, IMAGE, "portrait")
            assert app._dirty, "a failed autosave must retain its pending recovery write"
            await app._blocking(lambda: None)
            assert len(attempts) == 2 and not app._dirty
            recovered = project.open_project(project.autosave_path())
            assert recovered.data.artifacts == app.session.data.artifacts
            assert app._snapshot()["unsaved_changes"]  # recovery is not a user Save
        finally:
            await app.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("destination", ["new", "branch", "branch_roundtrip"])
def test_slow_import_cannot_cross_a_document_replacement(env, monkeypatch, destination):
    async def scenario():
        app = make_app()
        entered, release = threading.Event(), threading.Event()
        path = env / "portrait.png"
        path.write_bytes(IMAGE)
        original = server_app._read_import

        def read(path):
            entered.set()
            assert release.wait(5)
            return original(path)

        monkeypatch.setattr(server_app, "_read_import", read)
        pending = None
        try:
            if destination == "branch_roundtrip":
                await app._branches_create("user", "first")
                first = app.session.data.active_branch_id
            pending = asyncio.create_task(app._artifacts_import("user", path=str(path)))
            assert await asyncio.to_thread(entered.wait, 2)
            if destination == "new":
                await app._session_new("user", "replacement")
            else:
                await app._branches_create("user", "replacement")
                if destination == "branch_roundtrip":
                    await app._branches_switch("user", first)
            release.set()
            with pytest.raises(EngineError, match="session changed"):
                await pending
            assert not app.session.data.artifacts
            # An explicit retry against the current document still works.
            imported = await app._artifacts_import("user", path=str(path))
            assert imported["working"]["id"] in app.session.data.artifacts
        finally:
            release.set()
            if pending:
                await asyncio.gather(pending, return_exceptions=True)
            await app.close()

    asyncio.run(scenario())


def test_approval_edit_refuses_a_later_steps_output_and_keeps_waiting(env):
    async def scenario():
        app = make_app(approval_mode="ask_all")
        user, cli = Client(app), Client(app, "cli:codex")
        pending = None
        try:
            imported = await app._artifacts_import("user", data=base64.b64encode(IMAGE).decode())
            image = imported["working"]["id"]
            pending = asyncio.create_task(cli.call("tools.run", tool="filter",
                                                   params={"image": image, "names": ["invert"]}))
            sid = await user.waiting()
            later = await app._tools_run("user", "filter", {"image": image, "names": ["sepia"]})
            with pytest.raises(EngineError, match="makes it later"):
                await app._approval_respond("user", sid, "edit", {"image": later["outputs"][0],
                                                                 "names": ["invert"]})
            assert app._cli_gate.pending() == [sid]
            assert app.session.step(sid).params["image"] == image
            await app._approval_respond("user", sid, "approve")
            assert (await pending)["status"] == "done"
        finally:
            if pending and not pending.done():
                pending.cancel()
            if pending:
                await asyncio.gather(pending, return_exceptions=True)
            user.unsubscribe()
            cli.unsubscribe()
            await app.close()

    asyncio.run(scenario())


def test_session_run_also_guards_approval_edits(tmp_path):
    session = Session.new(output_dir=tmp_path)
    image = session.import_image(IMAGE, "portrait").id
    pending = session.propose("filter", {"image": image, "names": ["invert"]}, "agent:fake")
    later = session.run_tool("filter", {"image": image, "names": ["sepia"]}, "user")
    with pytest.raises(EngineError, match="makes it later"):
        session.run(pending.id, {"image": later.outputs[0], "names": ["invert"]})
    assert pending.status == "proposed" and pending.params["image"] == image


def test_replay_does_not_reuse_a_file_write(tmp_path):
    session = Session.new(output_dir=tmp_path)
    image = session.import_image(IMAGE, "portrait").id
    step = session.run_tool("export", {"image": image, "name": "exported"}, "user")
    assert step.status == "done"
    target = tmp_path / "exported.png"
    assert target.is_file()
    target.unlink()
    session.replay_from(step.id)
    assert step.status == "done" and target.is_file()
    assert target.read_bytes() == session.artifacts.data(image)
    session.replay_from(step.id)
    assert (tmp_path / "exported_2.png").is_file()  # never overwrite the prior export


def test_retry_announces_intervening_manual_changes_without_repeating_prompt(tmp_path):
    async def scenario():
        session = Session.new(output_dir=tmp_path)
        image = session.import_image(IMAGE, "portrait").id
        session.take_changes()
        provider = ScriptedProvider([ProviderError("temporary outage"), Reply(text="continued")])
        gate = ApprovalGate(lambda *_: None)
        cfg = TurnConfig(approval_mode="auto")
        assert await run_turn(session, provider, gate, "original request", [], cfg, lambda *_: None) == "provider_error"
        manual = session.run_tool("filter", {"image": image, "names": ["invert"]}, "user")
        assert await run_turn(session, provider, gate, "", [], cfg, lambda *_: None, retry=True) == "done"
        notes = [e["content"] for e in provider.received[-1] if e["role"] == "user"]
        assert any("the user ran step 1" in json.dumps(note) for note in notes)
        assert all("the user ran step 1" not in json.dumps(e["content"])
                   for e in provider.received[-1] if e["role"] == "system")
        assert len([m for m in session.data.messages if m.role == "user"]) == 1
        assert session.data.steps == [manual] and not session.changes

    asyncio.run(scenario())


def test_queued_auto_replay_does_not_run_in_another_branch(env):
    async def scenario():
        app = make_app(auto_replay=True)
        try:
            imported = await app._artifacts_import("user", data=base64.b64encode(IMAGE).decode())
            image = imported["working"]["id"]
            first = await app._tools_run("user", "filter", {"image": image, "names": ["invert"]})
            await app._branches_create("user", "variant")
            original = next(id for id, b in app.session.data.branches.items() if b.name == "Original")
            saved_step = app.session.data.branch_state(app.session.data.branches[original]).steps[0].model_dump()
            await app._lock.acquire()
            editing = asyncio.create_task(app._steps_edit("user", first["id"],
                                                         {"image": image, "names": ["sepia"]}))
            await asyncio.sleep(0)  # queue edit first
            switching = asyncio.create_task(app._branches_switch("user", original))
            await asyncio.sleep(0)  # branch switch must precede the replay the edit schedules
            app._lock.release()
            await asyncio.gather(editing, switching)
            await asyncio.gather(*list(app._tasks))
            assert app.session.data.active_branch_id == original
            assert app.session.data.steps[0].model_dump() == saved_step
        finally:
            await app.close()

    asyncio.run(scenario())


def test_explicit_replay_does_not_compete_with_automatic_replay(env):
    async def scenario():
        app = make_app(auto_replay=True)
        try:
            imported = await app._artifacts_import('user', data=base64.b64encode(IMAGE).decode())
            image = imported['working']['id']
            first = await app._tools_run('user', 'filter', {'image': image, 'names': ['invert']})
            await app._steps_edit('user', first['id'], {'image': image, 'names': ['grayscale']}, auto_replay=False)
            await asyncio.gather(*list(app._tasks))
            assert app.session.step(first['id']).status == 'stale'
            assert app.session.step(first['id']).outputs == first['outputs']
            result = await app._steps_replay_from('user', first['id'])
            assert result[0]['status'] == 'done'
            assert result[0]['outputs'] != first['outputs']
            assert len(app.session.data.steps) == 1
        finally:
            await app.close()

    asyncio.run(scenario())


def test_disconnect_during_cli_proposal_cannot_leave_an_orphan_approval(env, monkeypatch):
    async def scenario():
        app = make_app(approval_mode="ask_all")
        entered, release = threading.Event(), threading.Event()
        pending = None
        try:
            image = (await app._artifacts_import("user", data=base64.b64encode(IMAGE).decode()))["working"]["id"]
            save = project.autosave

            def delayed_save(session):
                if session.data.steps and session.data.steps[-1].status == "proposed":
                    entered.set()
                    assert release.wait(5)
                save(session)

            monkeypatch.setattr(project, "autosave", delayed_save)
            pending = asyncio.create_task(app._cli_call("cli:codex", "info", {"image": image}))
            assert await asyncio.to_thread(entered.wait, 2)
            assert app._cli_gate.pending() == []  # the proposal exists, its waiter does not
            app.on_client_gone()
            release.set()
            done, _ = await asyncio.wait({pending}, timeout=2)
            assert pending in done, "a disconnected UI must not leave a new approval waiting forever"
            assert (await pending)["status"] == "rejected"
            assert app._cli_gate.pending() == []
        finally:
            release.set()
            if pending and not pending.done():
                pending.cancel()
            if pending:
                await asyncio.gather(pending, return_exceptions=True)
            await app.close()

    asyncio.run(scenario())


def test_old_cli_cleanup_preserves_replacement_step_cancellation(env, monkeypatch):
    async def scenario():
        app = make_app(approval_mode="ask_all")
        user = Client(app)
        entered, release = asyncio.Event(), asyncio.Event()
        old_session = app.session
        settle = app._settle_owned
        tasks = []

        async def delayed_settle(session, step, note):
            if session is old_session:
                entered.set()
                await release.wait()
            return await settle(session, step, note)

        monkeypatch.setattr(app, "_settle_owned", delayed_settle)
        try:
            image = (await app._artifacts_import("user", data=base64.b64encode(IMAGE).decode()))["working"]["id"]
            old = asyncio.create_task(app._cli_call("cli:codex", "info", {"image": image}))
            tasks.append(old)
            old_id = await user.waiting()
            await app._session_new("user", "replacement")
            await asyncio.wait_for(entered.wait(), 2)
            image = (await app._artifacts_import("user", data=base64.b64encode(IMAGE).decode()))["working"]["id"]
            new = asyncio.create_task(app._cli_call("cli:codex", "info", {"image": image}))
            tasks.append(new)
            async with asyncio.timeout(2):
                while not app._cli_gate.pending():
                    await asyncio.sleep(0)
            new_id = app._cli_gate.pending()[0]
            assert old_id == new_id
            new_step = app.session.step(new_id)
            release.set()
            assert (await old)["status"] == "rejected"
            assert any(step is new_step and not cancel.is_set() for step, cancel in app._cli_cancels.values())
            assert app._cli_gate.pending() == [new_id]
            app._cli_gate.respond(new_id, "approve")
            assert (await new)["status"] == "done"
            assert not app._cli_cancels
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            user.unsubscribe()
            await app.close()
    asyncio.run(scenario())


def test_repeated_cli_cancellation_finishes_step_and_gate_cleanup(env):
    async def scenario():
        app = make_app(approval_mode="ask_all")
        user = Client(app)
        pending = None
        lock_held = False
        try:
            image = (await app._artifacts_import("user", data=base64.b64encode(IMAGE).decode()))["working"]["id"]
            pending = asyncio.create_task(app._cli_call("cli:codex", "info", {"image": image}))
            sid = await user.waiting()
            await app._lock.acquire()
            lock_held = True
            pending.cancel()
            await asyncio.sleep(0)  # first cancellation reaches cleanup waiting for the session lock
            pending.cancel()
            await asyncio.sleep(0)
            app._lock.release()
            lock_held = False
            await asyncio.gather(pending, return_exceptions=True)
            assert app.session.step(sid).status == "rejected"
            assert not app._cli_gate.pending()
            assert not app._cli_gate._waiting  # cancelled futures must not accumulate across retries
            assert not app._cli_cancels
        finally:
            if lock_held:
                app._lock.release()
            if pending and not pending.done():
                pending.cancel()
            if pending:
                await asyncio.gather(pending, return_exceptions=True)
            user.unsubscribe()
            await app.close()

    asyncio.run(scenario())
