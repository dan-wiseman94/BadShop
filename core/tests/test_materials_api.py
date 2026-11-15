import asyncio
import base64
import json
import threading
import uuid

import pytest

from badshop.engine import discovery
from badshop.server.settings import Settings
from test_discovery import encoded, fixture_web, hit, picture
from test_server_app import Client, Failed, env as env, imported, run


def test_material_search_acquire_and_early_edit_preserve_original_and_credits(env, monkeypatch):
    candidate = hit("https://example.org/poster.jpg", title="Poster")
    original = encoded(picture("blue"), "JPEG")
    monkeypatch.setitem(discovery.SEARCHERS, "commons", lambda query, count: [candidate])
    requests = fixture_web(monkeypatch, {"/thumb": original, "/poster.jpg": original})

    async def body(app):
        client = Client(app)
        prior = await imported(client)
        layout = await client.call("tools.run", tool="layout", params={
            "template": "comic", "images": [prior, prior], "captions": ["Original caption", "Other caption"],
        })
        before = await client.call("session.get")
        results = await client.call("materials.discover", params={"query": "Poster", "source": "commons"})
        assert results["candidates"][0]["source"]["creator"] == "Artist"
        assert results["candidates"][0]["thumbnail_data_url"].startswith("data:image/jpeg;base64,")
        after_search = await client.call("session.get")
        for key in ("steps", "artifacts", "manual_history", "document_revision"):
            assert after_search[key] == before[key]

        operation = uuid.uuid4().hex
        frame = json.dumps({"jsonrpc": "2.0", "id": 70, "method": "materials.acquire", "operation_id": operation,
                            "context": before["context"], "params": {
            "expected_revision": before["document_revision"],
            "params": {key: candidate["source"][key] for key in ("url", "title", "license", "creator", "page")}
                      | {"source_kind": "commons"},
        }})
        response = json.loads(await app.dispatcher.handle(frame, "user"))
        assert "result" in response, response
        result = response["result"]
        after_import = await client.call("session.get")
        assert result["operation_id"] == operation
        assert result["base_revision"] == before["document_revision"]
        assert result["result_revision"] == after_import["document_revision"]
        assert result["working"]["produced_by"] is None
        assert result["original"]["produced_by"] is None
        assert result["working"]["source"] == candidate["source"]
        assert base64.b64decode((await client.call("artifacts.get", id=result["original"]["id"]))["data"]) == original
        assert after_import["steps"] == before["steps"]
        assert after_import["manual_history"]["undo"] == "import online material"
        assert len(app.session.data.manual_undo) == 3
        assert json.loads(await app.dispatcher.handle(frame, "user")) == response
        assert (await client.call("operations.get", operation_id=operation))["result"] == result
        assert [url for url, _ in requests] == ["https://example.org/poster.jpg/thumb", "https://example.org/poster.jpg"]

        replacement = result["working"]["id"]
        edited = await client.call("steps.edit", step_id=layout["id"], replay="local",
                                   params={**layout["params"], "images": [prior, replacement],
                                           "captions": ["Original caption", "My typed caption"]})
        assert edited["replay"]["status"] == "done"
        saved = str(env / "material.badshop")
        await client.call("session.save_as", path=saved)
        reopened = await client.call("session.open", path=saved)
        assert len(reopened["steps"]) == 1
        assert reopened["steps"][0]["params"]["images"] == [prior, replacement]
        assert reopened["steps"][0]["params"]["captions"] == ["Original caption", "My typed caption"]
        assert reopened["artifacts"][replacement]["source"] == candidate["source"]
    run(body)


@pytest.mark.parametrize("replace_document", [False, True])
def test_material_acquire_refuses_after_document_changes_during_download(env, monkeypatch, replace_document):
    entered, release = threading.Event(), threading.Event()
    original = encoded(picture(), "JPEG")

    def fetch(url, **options):
        entered.set()
        assert release.wait(5), "test failed to release the paused download"
        return original, "image/jpeg"

    monkeypatch.setattr(discovery.sources, "http_get", fetch)

    async def body(app):
        client = Client(app)
        prior = await imported(client)
        before = await client.call("session.get")
        request = asyncio.create_task(client.call("materials.acquire", expected_revision=before["document_revision"],
                                                  params={"url": "https://example.org/delayed.jpg"}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if replace_document:
                await client.call("session.new", name="New picture")
            else:
                extra = await imported(client, encoded(picture("green")))
                assert extra != prior
            expected = await client.call("session.get")
        finally:
            release.set()
        with pytest.raises(Failed, match="session changed"):
            await request
        assert expected["artifacts"] == (await client.call("session.get"))["artifacts"]
        assert app.session.data.steps == []
    run(body)


def test_material_endpoints_refuse_cli_users_local_only_and_private_candidate_urls(env):
    async def body(app):
        client = Client(app)
        cli = Client(app, "cli:codex")
        params = {"url": "http://127.0.0.1/internal.png"}
        with pytest.raises(Failed, match="may not call"):
            await cli.call("materials.discover", params={"query": "poster"})
        with pytest.raises(Failed, match="may not call"):
            await cli.call("materials.acquire", params=params, expected_revision=0)
        with pytest.raises(Failed, match="local network"):
            await client.call("materials.acquire", params=params, expected_revision=0)
        await client.call("settings.set", values={"no_remote": True})
        with pytest.raises(Failed, match="Local only"):
            await client.call("materials.discover", params={"query": "poster"})
        with pytest.raises(Failed, match="Local only"):
            await client.call("materials.acquire", params=params, expected_revision=0)
        assert (await client.call("session.get"))["artifacts"] == {}
    run(body, Settings(no_remote=False))


def test_cancelled_and_invalid_downloads_leave_no_material_and_release_the_request_slot(env, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = encoded(picture(), "JPEG")

    def fetch(url, **options):
        if url.endswith("invalid.jpg"):
            return b"not an image", "image/jpeg"
        entered.set()
        assert release.wait(5), "test failed to release the paused download"
        return original, "image/jpeg"

    monkeypatch.setattr(discovery.sources, "http_get", fetch)

    async def body(app):
        client = Client(app)
        request = asyncio.create_task(client.call("materials.acquire", expected_revision=0,
                                                  params={"url": "https://example.org/cancel.jpg"}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            request.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(Failed, match="isn't an image"):
            await client.call("materials.acquire", expected_revision=0,
                              params={"url": "https://example.org/invalid.jpg"})
        snapshot = await client.call("session.get")
        assert snapshot["artifacts"] == {}
        assert snapshot["document_revision"] == 0
        assert snapshot["manual_history"]["undo"] is None
    run(body)


def test_local_and_saved_material_receipts_name_revision_and_artifact(env):
    async def body(app):
        client = Client(app)
        result = await client.call("artifacts.import", expected_revision=0, name="local.jpg",
                                   data=base64.b64encode(encoded(picture(), "JPEG")).decode())
        assert result["base_revision"] == 0
        assert result["result_revision"] == (await client.call("session.get"))["document_revision"]
        assert (await client.call("operations.get", operation_id=result["operation_id"]))["result"] == result
        saved = await client.call("library.save", artifact_id=result["working"]["id"], name="Saved poster")
        with pytest.raises(Failed, match="session changed"):
            await client.call("library.import", id=saved["id"], expected_revision=0)
        restored = await client.call("library.import", id=saved["id"], expected_revision=result["result_revision"])
        assert restored["base_revision"] == result["result_revision"]
        assert restored["result_revision"] == (await client.call("session.get"))["document_revision"]
        assert restored["working"]["id"] != result["working"]["id"]
        assert restored["working"]["blob_id"] == result["working"]["blob_id"]
        assert (await client.call("operations.get", operation_id=restored["operation_id"]))["result"] == restored
    run(body)


def test_disconnect_during_material_publication_commits_receipt(env, monkeypatch):
    original = encoded(picture(), "JPEG")
    fixture_web(monkeypatch, {"/poster.jpg": original})

    async def body(app):
        client = Client(app)
        entered, release = threading.Event(), threading.Event()
        imported_image = app.session.import_image

        def hold_publication(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return imported_image(*args, **kwargs)

        monkeypatch.setattr(app.session, "import_image", hold_publication)
        operation_id = uuid.uuid4().hex
        frame = json.dumps({
            "jsonrpc": "2.0", "id": 10, "method": "materials.acquire", "operation_id": operation_id,
            "params": {"params": {"url": "https://example.org/poster.jpg"}, "expected_revision": 0},
        })
        request = asyncio.create_task(app.dispatcher.handle(frame, "user"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            request.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        receipt = await client.call("operations.get", operation_id=operation_id)
        assert receipt["status"] == "committed"
        snapshot = await client.call("session.get")
        assert receipt["result"]["working"]["id"] in snapshot["artifacts"]
        assert receipt["result"]["result_revision"] == snapshot["document_revision"]
        assert snapshot["manual_history"]["undo"] == "import online material"

    run(body)
