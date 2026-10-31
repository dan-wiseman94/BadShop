"""Desktop document safety: autosave is not a user Save, and replacement is conditional."""

import asyncio

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
