"""Slow provider/keychain setup obeys Stop, disconnect, shutdown and lock lifetime."""

import asyncio
import threading

import pytest

from badshop.agent.fake import ScriptedProvider
from badshop.agent.provider import Reply
from badshop.engine.errors import EngineError
from badshop.server.app import CoreApp
from badshop.server.settings import Settings
from badshop.session.execution import InProcessExecutor
from test_server_app import env as env


def app_with_waiting_provider():
    app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
    entered, release = threading.Event(), threading.Event()
    provider = ScriptedProvider([Reply(text="Must not run after Stop")])

    def lookup():
        entered.set()
        assert release.wait(5), "test did not release provider lookup"
        app._provider = provider  # the fake-script loader also writes a cached provider
        return provider

    app._get_provider = lookup
    return app, entered, release, provider


@pytest.mark.parametrize("retry", [False, True])
def test_stop_invalidates_pending_provider_start(env, retry):
    async def scenario():
        app, entered, release, provider = app_with_waiting_provider()
        try:
            if retry:
                app._retry_session = app.session
                app.session.data.transcript = [{"role": "user", "content": "original"}]
                start = asyncio.create_task(app._chat_retry("user"))
            else:
                start = asyncio.create_task(app._chat_send("user", "go"))
            assert await asyncio.to_thread(entered.wait, 2)
            assert app._snapshot()["turn_running"] is True
            assert await app._chat_stop("user") == {"stopped": True}
            release.set()
            with pytest.raises(EngineError, match="start was stopped"):
                await start
            assert provider.received == []
            assert app._turn is None and not app._starting
            assert not app._snapshot()["turn_running"]
        finally:
            release.set()
            await app.close()

    asyncio.run(scenario())


def test_disconnect_invalidates_provider_start_synchronously(env):
    async def scenario():
        app, entered, release, provider = app_with_waiting_provider()
        try:
            start = asyncio.create_task(app._chat_send("user", "go"))
            assert await asyncio.to_thread(entered.wait, 2)
            app.on_client_gone()
            release.set()  # lookup may complete before the scheduled _stop_turn starts
            with pytest.raises(EngineError, match="start was stopped"):
                await start
            assert not provider.received
        finally:
            release.set()
            await app.close()

    asyncio.run(scenario())


def test_close_never_misses_a_turn_still_preparing(env):
    async def scenario():
        app, entered, release, provider = app_with_waiting_provider()
        try:
            start = asyncio.create_task(app._chat_send("user", "go"))
            assert await asyncio.to_thread(entered.wait, 2)
            closing = asyncio.create_task(app.close())
            await asyncio.sleep(0)
            assert app._closed
            release.set()
            with pytest.raises(EngineError, match="start was stopped"):
                await start
            await closing
            assert provider.received == []
            assert app._turn is None
            with pytest.raises(EngineError, match="closing"):
                await app._chat_send("user", "too late")
        finally:
            release.set()
            await app.close()

    asyncio.run(scenario())


def test_canceled_setup_keeps_lock_until_its_cache_write_is_over(env):
    async def scenario():
        app, entered, release, provider = app_with_waiting_provider()
        try:
            start = asyncio.create_task(app._chat_send("user", "go"))
            assert await asyncio.to_thread(entered.wait, 2)
            start.cancel()
            await asyncio.sleep(0)
            settings = asyncio.create_task(app._settings_set("user", {"fake_provider_script": "changed.json"}))
            await asyncio.sleep(0)
            assert app._lock.locked() and not settings.done()
            start.cancel()  # repeated cancellation must not release it either
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await start
            await settings
            assert app._provider is None  # settings reset happened after the old lookup wrote its cache
            assert provider.received == []
            assert not app._starting
        finally:
            release.set()
            await app.close()

    asyncio.run(scenario())


def test_provider_setup_reserves_session_and_prevents_another_start(env):
    async def scenario():
        app, entered, release, provider = app_with_waiting_provider()
        try:
            start = asyncio.create_task(app._chat_send("user", "go"))
            assert await asyncio.to_thread(entered.wait, 2)
            with pytest.raises(EngineError, match="still working"):
                await app._session_new("user", "replacement")
            with pytest.raises(EngineError, match="still working"):
                await app._chat_send("user", "second")
            assert app.session.data.name == "Untitled"
            release.set()
            assert await start == {"started": True}
            await app._turn
            assert len(provider.received) == 1
        finally:
            release.set()
            await app.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("stop", ["stop", "disconnect"])
def test_stop_also_invalidates_start_queued_behind_a_manual_tool(env, retry, stop):
    async def scenario():
        app, entered, release, provider = app_with_waiting_provider()
        release.set()  # this lookup must never run, but should fail fast if the regression returns
        try:
            if retry:
                app._retry_session = app.session
            async with app._lock:  # a manual tool owns the session when chat.send arrives
                start = asyncio.create_task(app._chat_retry("user") if retry
                                            else app._chat_send("user", "queued"))
                await asyncio.sleep(0)
                assert not entered.is_set() and not app._starting
                if stop == "stop":
                    await app._chat_stop("user")
                else:
                    app.on_client_gone()
            with pytest.raises(EngineError, match="start was stopped"):
                await start
            assert not entered.is_set()
            assert provider.received == []
            assert app._turn is None
        finally:
            await app.close()

    asyncio.run(scenario())
