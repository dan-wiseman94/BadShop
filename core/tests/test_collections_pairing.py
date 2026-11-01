"""Collection contracts and geometry comparisons without network dependence."""
import json
import urllib.parse

import pytest
from PIL import Image, ImageDraw

from badshop.engine import discovery, pairing, sources
from badshop.engine.errors import EngineError
from memstore import MemoryStore


def replies(monkeypatch, responder):
    calls = []
    def get(url, **kwargs):
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qs(parsed.query)
        calls.append((parsed.path, params))
        return json.dumps(responder(parsed.path, params)).encode(), "application/json"
    monkeypatch.setattr(sources, "http_get", get)
    return calls


def test_smithsonian_media_rights_not_metadata_rights(monkeypatch):
    monkeypatch.setenv("BADSHOP_SMITHSONIAN_API_KEY", "secret")
    def response(path, params):
        assert params["api_key"] == ["secret"]
        assert "media_usage:CC0" in params["q"][0]
        return {"status": 200, "response": {"rows": [{"title": "Ancient cat", "content": {
            "freetext": {"name": [{"label": "Artist", "content": "A. Maker"}]},
            "descriptiveNonRepeating": {"guid": "https://example.org/object", "metadata_usage": {"access": "CC0"},
            "online_media": {"media": [
                {"type": "Images", "usage": {"access": "restricted"}, "content": "https://example.org/no.jpg"},
                {"type": "Images", "usage": {"access": "CC0"}, "content": "https://example.org/view.jpg",
                 "resources": [{"label": "High-resolution JPEG", "url": "https://example.org/orig.jpg"},
                               {"label": "Thumbnail Image", "url": "https://example.org/small.jpg"}]}]}}}}]}}
    replies(monkeypatch, response)
    hits = discovery.smithsonian("cat", 2)
    assert len(hits) == 1
    assert hits[0]["url"].endswith("orig.jpg") and hits[0]["thumbnail"].endswith("small.jpg")
    assert hits[0]["source"]["license"] == "CC0 1.0"
    assert hits[0]["source"]["creator"] == "A. Maker"
    assert "secret" not in json.dumps(hits)


def test_europeana_original_and_rights(monkeypatch):
    monkeypatch.setenv("BADSHOP_EUROPEANA_API_KEY", "secret")
    calls = replies(monkeypatch, lambda path, params: {"success": True, "items": [
        {"title": ["Old advert"], "edmPreview": ["https://example.org/thumb.jpg"],
         "edmIsShownBy": ["https://example.org/orig.jpg"], "edmIsShownAt": ["https://example.org/item"],
         "rights": ["https://creativecommons.org/publicdomain/mark/1.0/"], "dcCreator": ["Maker"]},
        {"title": ["Preview only"], "edmPreview": ["https://example.org/preview.jpg"]}]})
    hits = discovery.europeana("advert", 2)
    assert len(hits) == 1 and hits[0]["source"]["creator"] == "Maker"
    assert hits[0]["source"]["license"].endswith("mark/1.0/")
    assert calls[0][1]["reusability"] == ["open"]
    assert calls[0][1]["qf"] == ["TYPE:IMAGE"]


def test_bhl_illustrations_keep_page_provenance(monkeypatch):
    monkeypatch.setenv("BADSHOP_BHL_API_KEY", "secret")
    def response(path, params):
        if params["op"][0] == "PublicationSearch":
            return {"Status": "ok", "Result": [
                {"BHLType": "Item", "ItemID": "1", "Title": "Birds", "Authors": [{"Name": "Artist"}]},
                {"BHLType": "Part", "PartID": "2", "Title": "Owls"}]}
        suffix = params["id"][0]
        return {"Status": "ok", "Result": [{"LicenseUrl": "https://example.org/license", "Pages": [
            {"PageID": "text", "PageTypes": [{"PageTypeName": "Text"}], "FullSizeImageUrl": "https://example.org/text"},
            {"PageID": suffix, "PageTypes": [{"PageTypeName": "Illustration"}],
             "PageNumbers": [{"Prefix": "Plate", "Number": suffix}],
             "FullSizeImageUrl": f"https://example.org/pageimage/{suffix}",
             "ThumbnailUrl": f"https://example.org/pagethumb/{suffix}",
             "PageUrl": f"https://example.org/page/{suffix}"}]}]}
    calls = replies(monkeypatch, response)
    hits = discovery.bhl("birds", 4)
    assert len(hits) == 2 and hits[0]["title"] == "Birds — Plate 1"
    assert hits[0]["source"]["page"] == "https://example.org/page/1"
    assert hits[0]["source"]["license"] == "https://example.org/license"
    assert {c[1]["op"][0] for c in calls} == {"PublicationSearch", "GetItemMetadata", "GetPartMetadata"}


@pytest.mark.parametrize("name", ["smithsonian", "bhl", "europeana"])
def test_collection_keys_and_failures_do_not_leak_credentials(monkeypatch, name):
    env = f"BADSHOP_{name.upper()}_API_KEY"
    monkeypatch.delenv(env, raising=False)
    with pytest.raises(EngineError, match=env):
        discovery.SEARCHERS[name]("cat", 1)
    monkeypatch.setenv(env, "super-secret")
    def fail(*args, **kwargs):
        raise OSError("request failed ?api_key=super-secret")
    monkeypatch.setattr(sources, "http_get", fail)
    with pytest.raises(EngineError) as exc:
        discovery.SEARCHERS[name]("cat", 1)
    assert "super-secret" not in str(exc.value)


def test_pairing_geometry_and_reusable_coordinates(monkeypatch):
    monkeypatch.setattr(pairing, "_faces", lambda im: [])
    store = MemoryStore()
    tall = store.add(Image.new("RGB", (50, 100), "red"), "tall.png")
    wide = store.add(Image.new("RGB", (100, 30), "blue"), "wide.png")
    scene = store.add(Image.new("RGB", (300, 200), "white"), "scene.png")
    p = pairing.PairImagesParams(donors=[wide, tall], backgrounds=[scene], target_box=(100, 10, 150, 110))
    result = pairing.pair_images(p, store)
    assert result.data["pairs"][0]["donor"] == tall
    assert result.data["pairs"][0]["paste_params"] == {"base": scene, "piece": tall, "fit_box": [100, 10, 150, 110]}
    assert [o.key for o in result.outputs] == ["sheet"]
    assert pairing.pair_images(p, store).outputs[0].encode() == result.outputs[0].encode()


def test_pair_preview_hard_alpha_leaves_inputs_unchanged():
    base = Image.new("RGB", (100, 100), "white")
    donor = Image.new("RGBA", (20, 20), (255, 0, 0, 127))
    ImageDraw.Draw(donor).rectangle((10, 0, 19, 19), fill=(255, 0, 0, 128))
    original = donor.tobytes()
    preview = pairing._preview(base, donor, (20, 20, 40, 40))
    assert set(preview.get_flattened_data()) <= {(255, 255, 255), (255, 0, 0)}
    assert donor.tobytes() == original and base.getpixel((25, 25)) == (255, 255, 255)


def test_head_targets_and_explicit_override(monkeypatch):
    monkeypatch.setattr(pairing, "_faces", lambda im: [(30, 40, 20, 30)])
    store = MemoryStore()
    donor = store.add(Image.new("RGB", (100, 100), "red"))
    scene = store.add(Image.new("RGB", (200, 200), "white"))
    result = pairing.pair_images(pairing.PairImagesParams(donors=[donor], backgrounds=[scene], role="head"), store)
    assert result.data["pairs"][0]["paste_params"]["fit_box"] == [27, 31, 53, 73]
    result = pairing.pair_images(pairing.PairImagesParams(donors=[donor], backgrounds=[scene], role="head", target_box=(1, 2, 30, 40)), store)
    assert result.data["pairs"][0]["paste_params"]["fit_box"] == [1, 2, 30, 40]


def test_pairing_rejects_identical_or_outside_targets(monkeypatch):
    monkeypatch.setattr(pairing, "_faces", lambda im: [])
    store = MemoryStore()
    a = store.add(Image.new("RGB", (50, 50)))
    b = store.add(Image.new("RGB", (50, 50)))
    for params in [dict(donors=[a], backgrounds=[a]), dict(donors=[a], backgrounds=[b], target_box=(90, 90, 100, 100))]:
        with pytest.raises(EngineError, match="no usable image pairs"):
            pairing.pair_images(pairing.PairImagesParams(**params), store)
