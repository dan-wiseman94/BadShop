"""Key-free collection contracts and secret-free source capability reporting."""

import copy
import io
import json
import urllib.parse

import pytest
from PIL import Image

from badshop.engine import discovery, sources


def api(monkeypatch, response):
    calls = []
    def get(url, **options):
        calls.append((url, options))
        return json.dumps(response).encode(), "application/json"
    monkeypatch.setattr(sources, "http_get", get)
    return calls


def artwork(**updates):
    return {"id": 1, "title": "Cat", "share_license_status": "CC0",
            "url": "https://clevelandart.org/art/1", "creators": [{"description": "Artist"}],
            "images": {"web": {"url": "https://example.org/web.jpg"},
                       "print": {"url": "https://example.org/print.jpg"},
                       "full": {"url": "https://example.org/huge.tif"}}, **updates}


def wellcome_image(license="cc-by", status="open", **updates):
    return {"id": "image1", "aspectRatio": 1.5,
            "source": {"id": "work1", "title": "Old medical poster",
                       "contributors": [{"agent": {"label": "Artist"}}]},
            "locations": [{"url": "https://iiif.wellcomecollection.org/image/ID/info.json",
                           "locationType": {"id": "iiif-image"}, "credit": "Artist",
                           "license": {"id": license, "url": "https://creativecommons.org/licenses/by/4.0/"},
                           "accessConditions": [{"status": {"id": status}}]}], **updates}


def test_cleveland_verifies_image_rights_and_uses_print_jpeg(monkeypatch):
    calls = api(monkeypatch, {"data": [artwork(share_license_status="Copyrighted"),
        artwork(images=None), artwork(images={"web": {"url": "file:///private"}}), artwork()]})
    hits = discovery.cleveland("cat", 3)
    assert len(hits) == 1
    assert hits[0]["url"] == "https://example.org/print.jpg"
    assert hits[0]["thumbnail"] == "https://example.org/web.jpg"
    assert hits[0]["source"] == sources.provenance("cleveland", hits[0]["url"],
        title="Cat", page="https://clevelandart.org/art/1", license="CC0 1.0", creator="Artist")
    assert len(calls) == 1
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0][0]).query)
    assert params["cc0"] == params["has_image"] == ["1"]
    assert params["limit"] == ["6"]
    assert "images" in params["fields"][0]
    assert calls[0][1] == {"timeout": 8, "max_bytes": sources.MAX_TEXT}


def test_cleveland_supports_missing_print_and_skips_malformed_rows(monkeypatch):
    api(monkeypatch, {"data": [None, "not a row", artwork(images={"web": {"url": "https://example.org/web.jpg"}}, creators=None)]})
    hits = discovery.cleveland("cat", 2)
    assert len(hits) == 1 and hits[0]["url"] == hits[0]["thumbnail"]
    assert hits[0]["source"]["creator"] is None


def test_wellcome_checks_each_location_rights_access_and_iiif_type(monkeypatch):
    good = wellcome_image()
    good["locations"].insert(0, {"url": "https://example.org/manifest.json", "locationType": {"id": "iiif-presentation"}})
    calls = api(monkeypatch, {"results": [wellcome_image(license="inc"), wellcome_image(status="restricted"), good]})
    hits = discovery.wellcome("poster", 3)
    assert len(hits) == 1
    hit = hits[0]
    assert hit["url"].endswith("/full/full/0/default.jpg")
    assert hit["thumbnail"].endswith("/full/320,/0/default.jpg")
    assert hit["source"]["creator"] == "Artist"  # credit and contributor are deduplicated
    assert hit["source"]["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert hit["page"] == "https://wellcomecollection.org/images/image1"
    assert len(calls) == 1
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0][0]).query)
    assert params["locations.license"] == ["cc0,pdm,cc-by,cc-by-sa"]
    assert params["include"] == ["source.contributors"] and params["pageSize"] == ["6"]


def test_wellcome_portrait_preview_and_missing_optional_metadata(monkeypatch):
    row = wellcome_image(aspectRatio=0.5, source=None)
    row["locations"][0]["credit"] = None
    api(monkeypatch, {"results": [None, {"locations": "bad"}, row]})
    hit = discovery.wellcome("print", 2)[0]
    assert hit["thumbnail"].endswith("/full/,320/0/default.jpg")
    assert hit["source"]["creator"] is None and hit["title"] == "Untitled"


@pytest.mark.parametrize("source,records_key,record", [
    ("cleveland", "data", artwork()), ("wellcome", "results", wellcome_image()),
])
def test_new_sources_bound_records_and_accept_acquisition_metadata(monkeypatch, source, records_key, record):
    calls = api(monkeypatch, {records_key: [copy.deepcopy(record) for _ in range(100)]})
    hits = discovery.SEARCHERS[source]("cat", 2)
    assert len(hits) == 2 and len(calls) == 1
    assert discovery.DiscoverParams(query="cat", source=source).source == source
    for hit in hits:
        assert discovery.AcquireParams(url=hit["url"], source_kind=source, page=hit["page"],
            title=hit["title"], license=hit["source"]["license"], creator=hit["source"]["creator"])


@pytest.mark.parametrize("source,records_key,record", [
    ("cleveland", "data", artwork()), ("wellcome", "results", wellcome_image()),
])
def test_new_collection_discovery_fetches_preview_until_selected(monkeypatch, source, records_key, record):
    calls = []
    preview, original = Image.new("RGB", (320, 240), "red"), Image.new("RGB", (800, 600), "blue")
    def get(url, **options):
        calls.append(url)
        if "/api/artworks/" in url or "/catalogue/v2/images" in url:
            return json.dumps({records_key: [record]}).encode(), "application/json"
        image = original if ("/print.jpg" in url or "/full/full/" in url) else preview
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue(), "image/png"
    monkeypatch.setattr(sources, "http_get", get)
    result = discovery.discover(discovery.DiscoverParams(query="cat", source=source, n=1))
    candidate = result.data["candidates"][0]
    assert len(result.outputs) == 1 and candidate["thumbnail_data_url"].startswith("data:image/jpeg;")
    assert candidate["url"] not in calls and candidate["thumbnail"] in calls
    fetched = discovery.acquire(discovery.AcquireParams(url=candidate["url"], source_kind=source,
        page=candidate["page"], title=candidate["title"], license=candidate["source"]["license"],
        creator=candidate["source"]["creator"]))
    assert fetched.outputs[0].image.size == (800, 600)
    assert fetched.data["sources"][0] == candidate["source"]


def test_source_status_reports_configuration_without_values_or_requests(monkeypatch):
    for _, env, _ in discovery.SOURCE_CONFIG.values():
        if env:
            monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("BADSHOP_FLICKR_API_KEY", "private-test-key")
    monkeypatch.setenv("BADSHOP_IMAGE_SEARCH_URL", "https://private-gateway.example/images")
    monkeypatch.setenv("BADSHOP_BHL_API_KEY", "   ")
    monkeypatch.setattr(sources, "http_get", lambda *a, **kw: pytest.fail("status must not contact sources"))
    rows = discovery.source_status()
    status = {row["id"]: row for row in rows}
    assert set(status) == set(discovery.SEARCHERS)
    assert all(set(row) == {"id", "name", "configured", "requires_key", "env_var"} for row in rows)
    assert status["cleveland"]["configured"] and status["wellcome"]["configured"]
    assert status["cleveland"]["env_var"] is None and not status["wellcome"]["requires_key"]
    assert status["flickr"]["configured"] and status["flickr"]["requires_key"]
    assert not status["bhl"]["configured"]
    assert status["web"]["configured"] and not status["web"]["requires_key"]
    assert "private-test-key" not in json.dumps(rows) and "private-gateway" not in json.dumps(rows)


def test_all_searches_both_key_free_collections(monkeypatch):
    calls = []
    for _, env, _ in discovery.SOURCE_CONFIG.values():
        if env:
            monkeypatch.delenv(env, raising=False)
    for name in discovery.SEARCHERS:
        def search(query, n, source=name):
            calls.append(source)
            return [discovery._candidate(source, f"https://example.org/{source}")]
        monkeypatch.setitem(discovery.SEARCHERS, name, search)
    image = Image.new("RGB", (50, 40))
    monkeypatch.setattr(discovery, "_preview", lambda hit: (hit | {"width": 50, "height": 40}, image, discovery.fingerprint(image)))
    discovery.discover(discovery.DiscoverParams(query="cat", n=1))
    assert set(calls) == {"commons", "openverse", "loc", "met", "nasa", "cleveland", "wellcome"}
