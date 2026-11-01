"""Discovery preserves selected originals and ranks previews without polluting session artifacts."""

import io
import json
import urllib.parse

import pytest
from PIL import Image, ImageDraw

from badshop.engine import discovery, sources
from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from memstore import MemoryStore


def encoded(image, fmt="PNG"):
    stream = io.BytesIO()
    image.save(stream, fmt)
    return stream.getvalue()


def picture(color="red", offset=0):
    image = Image.new("RGB", (240, 280), color)
    ImageDraw.Draw(image).ellipse((20 + offset, 30, 180 + offset, 230), fill="white")
    return image


def hit(url, title="Lincoln portrait", kind="commons"):
    return discovery._candidate(kind, url, thumbnail=url + "/thumb", title=title,
                                page="https://example.org/source", license="CC0", creator="Artist")


def fixture_web(monkeypatch, routes):
    requests = []
    def get(url, **kwargs):
        requests.append((url, kwargs))
        for key, value in routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return (json.dumps(value).encode(), "application/json") if isinstance(value, (dict, list)) else (value, "image/png")
        raise OSError("unexpected request")
    monkeypatch.setattr(sources, "http_get", get)
    return requests


def test_discovery_only_imports_sheet_and_removes_recompressed_duplicate(monkeypatch):
    original = picture()
    monkeypatch.setitem(discovery.SEARCHERS, "commons", lambda q, n: [
        hit("https://example.org/a"), hit("https://example.org/b"),
        hit("https://example.org/c", "Lincoln full body")])
    fixture_web(monkeypatch, {"/a/thumb": encoded(original), "/b/thumb": encoded(original, "JPEG"),
                             "/c/thumb": encoded(picture("blue", 30))})
    store = MemoryStore()
    result = run_tool("discover", {"query": "Lincoln", "source": "commons", "n": 3}, store).result
    assert [o.key for o in result.outputs] == ["sheet"]
    assert len(result.data["candidates"]) == 2
    assert result.data["duplicates_removed"] == 1
    assert result.data["sources"] == [None]
    for candidate in result.data["candidates"]:
        assert candidate["thumbnail_data_url"].startswith("data:image/jpeg;base64,")
        assert candidate["source"]["creator"] == "Artist"
        assert candidate["number"] in (1, 2)


def test_subject_category_uses_exact_entity_not_related_articles(monkeypatch):
    requests = fixture_web(monkeypatch, {
        "en.wikipedia.org": {"query": {"pages": {"1": {"pageprops": {"wikibase_item": "Q91"}}}}},
        "wikidata.org": {"entities": {"Q91": {"claims": {"P373": [{"mainsnak": {"datavalue": {"value": "Abraham Lincoln"}}}]}}}},
        "commons.wikimedia": {"query": {"pages": {"9": {"title": "File:Lincoln.jpg", "imageinfo": [{
            "mime": "image/jpeg", "url": "https://example.org/original.jpg", "thumburl": "https://example.org/thumb.jpg"}]}}}},
    })
    found = discovery.subject_commons("Abraham Lincoln", 6)
    assert found[0]["url"].endswith("original.jpg")
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[-1][0]).query)
    assert params["generator"] == ["categorymembers"]
    assert params["gcmtitle"] == ["Category:Abraham Lincoln"]


def test_same_subject_without_category_falls_back_to_exact_phrase(monkeypatch):
    fixture_web(monkeypatch, {"wikipedia.org": {"query": {"pages": {"-1": {"missing": ""}}}}})
    calls = []
    monkeypatch.setattr(discovery, "commons", lambda q, n: calls.append(q) or [])
    discovery.subject_commons("Lincoln", 3)
    assert calls == ['"Lincoln"']


def test_filters_exclusions_and_searches_requested_shot(monkeypatch):
    queries = []
    monkeypatch.setitem(discovery.SEARCHERS, "commons", lambda q, n: queries.append(q) or [
        hit("https://example.org/no"), hit("https://example.org/yes")])
    fixture_web(monkeypatch, {"/yes/thumb": encoded(picture())})
    result = discovery.discover(discovery.DiscoverParams(query="Lincoln", pose="facing left", expression="smiling",
        purpose="head", source="commons", exclude_urls=["https://example.org/no"]))
    assert queries == ["Lincoln facing left smiling"]
    assert [c["url"] for c in result.data["candidates"]] == ["https://example.org/yes"]
    assert "portrait-friendly frame" in result.data["candidates"][0]["reasons"]


def test_partial_source_failure_keeps_other_candidates(monkeypatch):
    def fail(q, n):
        raise OSError("server failure")
    for name in discovery.SEARCHERS:
        monkeypatch.setitem(discovery.SEARCHERS, name, fail)
    monkeypatch.setitem(discovery.SEARCHERS, "nasa", lambda q, n: [hit("https://example.org/good", kind="nasa")])
    fixture_web(monkeypatch, {"/good/thumb": encoded(picture())})
    result = discovery.discover(discovery.DiscoverParams(query="moon"))
    assert len(result.data["candidates"]) == 1
    assert "commons: source unavailable" in result.data["warnings"]


def test_no_candidates_is_actionable(monkeypatch):
    monkeypatch.setitem(discovery.SEARCHERS, "commons", lambda q, n: [])
    with pytest.raises(EngineError, match="no usable image previews") as exc:
        discovery.discover(discovery.DiscoverParams(query="unknown", source="commons"))
    assert "fewer words" in exc.value.hint


def test_acquire_imports_original_and_preserves_credit(monkeypatch):
    image = picture()
    fixture_web(monkeypatch, {"https://example.org/original": encoded(image)})
    result = run_tool("acquire", {"url": "https://example.org/original", "source_kind": "met",
        "page": "https://example.org/page", "title": "Portrait", "creator": "Painter", "license": "CC0"}, MemoryStore()).result
    assert result.outputs[0].image.tobytes() == image.tobytes()
    assert result.data["sources"] == [sources.provenance("met", "https://example.org/original",
        page="https://example.org/page", title="Portrait", creator="Painter", license="CC0")]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "data:image/png;base64,AA", "ftp://example.org/a"])
def test_acquire_rejects_nonweb_urls(url):
    with pytest.raises(EngineError, match="only http"):
        discovery.acquire(discovery.AcquireParams(url=url))


def test_loc_handles_missing_and_multiple_images(monkeypatch):
    fixture_web(monkeypatch, {"loc.gov": {"results": [
        {"title": "No image"}, {"title": "Dog", "image_url": ["https://example.org/small", "https://example.org/large"],
                               "url": "https://www.loc.gov/item/1/", "contributor": ["Photographer"], "rights": ["Public domain"]}]}})
    result = discovery.loc("dog", 4)
    assert len(result) == 1
    assert result[0]["url"].endswith("large") and result[0]["thumbnail"].endswith("small")
    assert result[0]["source"]["creator"] == "Photographer"


def test_met_keeps_only_public_domain_images(monkeypatch):
    fixture_web(monkeypatch, {"/search": {"objectIDs": [1, 2]},
        "/objects/1": {"isPublicDomain": True, "primaryImage": "https://example.org/large", "primaryImageSmall": "https://example.org/small", "title": "Painting"},
        "/objects/2": {"isPublicDomain": False, "primaryImage": "https://example.org/restricted"}})
    result = discovery.met("painting", 2)
    assert len(result) == 1 and result[0]["source"]["license"] == "CC0 1.0"


def test_nasa_preview_and_acquire_resolve_original(monkeypatch):
    requests = fixture_web(monkeypatch, {"/search": {"collection": {"items": [
        {"data": [{"nasa_id": "ABC 123", "title": "Moon", "center": "JSC"}], "links": [{"rel": "preview", "href": "https://example.org/preview.jpg"}]}]}},
        "/asset/": {"collection": {"items": [{"href": "https://example.org/photo~orig.jpg"}]}},
        "photo~orig.jpg": encoded(picture())})
    candidate = discovery.nasa("moon", 3)[0]
    result = discovery.acquire(discovery.AcquireParams(url=candidate["url"], source_kind="nasa", page=candidate["page"]))
    assert result.data["sources"][0]["url"].endswith("~orig.jpg")
    assert any("ABC%20123" in url for url, _ in requests)


def test_flickr_key_never_escapes_failed_request(monkeypatch):
    monkeypatch.setenv("BADSHOP_FLICKR_API_KEY", "private-key")
    fixture_web(monkeypatch, {"flickr.com": OSError("https://flickr.com/?api_key=private-key")})
    with pytest.raises(EngineError) as exc:
        discovery.flickr("cat", 3)
    assert "private-key" not in str(exc.value)


def test_flickr_commons_restricts_search_and_preserves_rights(monkeypatch):
    monkeypatch.setenv("BADSHOP_FLICKR_API_KEY", "private-key")
    requests = fixture_web(monkeypatch, {"flickr.com": {"photos": {"photo": [
        {"id": "1", "owner": "archive", "ownername": "Archive", "license": "7", "url_m": "https://example.org/m", "url_l": "https://example.org/l"}]}}})
    result = discovery.flickr("cat", 3)
    assert "is_commons=true" in requests[0][0]
    assert result[0]["source"]["license"] == "No known copyright restrictions"
    assert "private-key" not in json.dumps(result)


def test_web_connector_is_opt_in_and_uses_small_contract(monkeypatch):
    monkeypatch.delenv("BADSHOP_IMAGE_SEARCH_URL", raising=False)
    with pytest.raises(EngineError, match="BADSHOP_IMAGE_SEARCH_URL"):
        discovery.web("cat", 2)
    monkeypatch.setenv("BADSHOP_IMAGE_SEARCH_URL", "https://search.example.org/images")
    requests = fixture_web(monkeypatch, {"search.example": {"results": [{"url": "https://example.org/cat", "title": "Cat"}]}})
    assert discovery.web("cat", 2)[0]["source"]["kind"] == "web"
    assert "limit=2" in requests[0][0]


def test_reference_preview_changes_similarity_order_without_import(monkeypatch):
    red, blue = picture("red"), picture("blue", 30)
    monkeypatch.setitem(discovery.SEARCHERS, "commons", lambda q, n: [hit("https://example.org/blue"), hit("https://example.org/red")])
    fixture_web(monkeypatch, {"/red": encoded(red), "/blue": encoded(blue)})
    params = {"query": "Lincoln", "source": "commons", "reference_url": "https://example.org/red/thumb"}
    similar = discovery.discover(discovery.DiscoverParams(**params, variation="similar"))
    different = discovery.discover(discovery.DiscoverParams(**params, variation="different"))
    assert similar.data["candidates"][0]["url"].endswith("red")
    assert different.data["candidates"][0]["url"].endswith("blue")
    assert len(similar.outputs) == len(different.outputs) == 1


def test_subject_category_endpoint_failure_falls_back_to_commons(monkeypatch):
    fixture_web(monkeypatch, {"wikipedia.org": OSError("offline")})
    calls = []
    monkeypatch.setattr(discovery, "commons", lambda q, n: calls.append(q) or [hit("https://example.org/lincoln")])
    assert len(discovery.subject_commons("Lincoln", 3)) == 1
    assert calls == ['"Lincoln"']


def test_nasa_failed_original_download_keeps_preview(monkeypatch):
    fixture_web(monkeypatch, {
        "/asset/": {"collection": {"items": [{"href": "https://example.org/missing~orig.jpg"}]}},
        "missing~orig.jpg": OSError("not available"),
        "preview.jpg": encoded(picture()),
    })
    result = discovery.acquire(discovery.AcquireParams(url="https://example.org/preview.jpg", source_kind="nasa",
        page="https://images.nasa.gov/details/ABC"))
    assert result.data["sources"][0]["url"] == "https://example.org/preview.jpg"
    assert any("inspected preview" in line for line in result.lines)


def test_met_uses_paginated_search_after_old_endpoint_retirement(monkeypatch):
    requests = fixture_web(monkeypatch, {"/search": {"objectIDs": []}})
    assert discovery.met("cat", 4) == []
    assert "/v1.1/search?" in requests[0][0]
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0][0]).query)
    assert params["limit"] == ["4"] and params["offset"] == ["0"]


def test_candidate_metadata_cannot_supply_executable_page_link():
    candidate = discovery._candidate("web", "https://example.org/image", page="javascript:alert(1)", creator="artist\x1b[31m")
    assert candidate["page"] is None
    assert "\x1b" not in candidate["source"]["creator"]


def test_candidate_metadata_fits_acquisition_parameter_limits():
    candidate = discovery._candidate("web", "https://example.org/image", title="t" * 1000,
                                     creator="a" * 1000, license="l" * 1000)
    source = candidate["source"]
    params = discovery.AcquireParams(url=candidate["url"], source_kind=source["kind"],
        page=source["page"], title=source["title"], license=source["license"], creator=source["creator"])
    assert len(params.creator) == len(params.license) == len(params.title) == 500


def test_preview_decoding_has_small_concurrent_pixel_budget(monkeypatch):
    fixture_web(monkeypatch, {"/big/thumb": encoded(Image.new("RGB", (2500, 2000)))})
    assert discovery._preview(hit("https://example.org/big")) is None
