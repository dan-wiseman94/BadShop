"""Structured provenance for fetched images (carry-forward SP F4, spec §6 Artifact.source).

Every source tool's `data["sources"]` lines up with its outputs: one dict per downloaded image, None for
the contact sheet. Nothing is parsed from captions, and the CLI's stdout and files do not change (the
offline parity tests in test_sources.py pin that)."""

import json
import re
import urllib.error

import pytest

from badshop.engine import sources
from badshop.tools.runner import run_tool
from conftest import FIXTURES
from memstore import MemoryStore
from test_sources import API, fake_http, first_commons_url

KEYS = ["kind", "url", "page", "title", "license", "creator"]
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
NOTHING = dict.fromkeys(KEYS)  # every key None


def aligned(run) -> list[dict | None]:
    """data["sources"], after checking it matches the outputs and holds only JSON-safe strings (stripped,
    non-blank, no control characters, encodable as UTF-8) or None."""
    found = run.result.data["sources"]
    assert len(found) == len(run.result.outputs)
    for out, s in zip(run.result.outputs, found):
        if out.key == "sheet":
            assert s is None
            continue
        assert list(s) == KEYS
        assert all(v is None or (isinstance(v, str) and v and v == v.strip() and not CONTROL.search(v))
                   for v in s.values()), s
    assert json.loads(json.dumps(run.result.data)) == run.result.data
    json.dumps(run.result.data, ensure_ascii=False).encode("utf-8")  # a lone surrogate would raise here
    return found


@pytest.fixture
def web(monkeypatch):
    requested: list[str] = []
    monkeypatch.setattr(sources, "http_get", fake_http(requested))
    return requested


def test_fetch_search_sources_line_up_with_outputs(web):
    run = run_tool("fetch", {"query": "golden retriever", "n": 4}, MemoryStore())
    found = aligned(run)
    assert [o.key for o in run.result.outputs] == ["1", "2", "3", "4", "sheet"]
    assert [s and s["kind"] for s in found] == ["commons", "openverse", "commons", "openverse", None]
    assert sources.SOURCE_KEYS == tuple(KEYS)
    assert found[0] == {  # the recorded Commons reply predates extmetadata: no licence or creator in it
        "kind": "commons", "url": first_commons_url(),
        "page": ("https://commons.wikimedia.org/wiki/File:"
                 "D%C3%BClmen,_Hausd%C3%BClmen,_Golden_Retriever_--_2022_--_5945.jpg"),
        "title": "Dülmen, Hausdülmen, Golden Retriever -- 2022 -- 5945.jpg", "license": None, "creator": None}
    assert found[1] == {
        "kind": "openverse", "url": "https://live.staticflickr.com/4040/4302649500_71d456b338_b.jpg",
        "page": "https://www.flickr.com/photos/47544801@N00/4302649500", "title": "Golden Retriever",
        "license": "CC BY-NC 2.0", "creator": "rkleine"}
    assert run.result.outputs[1].caption.endswith("  [openverse, BY-NC 2.0, by rkleine]")  # as before
    assert "iiprop=url%7Cmime%7Csize%7Cextmetadata" in web[0]
    assert "iiextmetadatafilter=LicenseShortName%7CArtist" in web[0]


# Real extmetadata of three recorded Commons hits (read from the live API on 2026-09-27); the fourth
# is damaged on purpose: values that are not strings never reach the provenance.
COMMONS_META = {
    "192179542": ('<bdi><a href="https://www.wikidata.org/wiki/Q34788025" class="extiw" title="d:Q34788025">'
                  '<span title="German photographer and mathematician">Dietmar Rabich</span></a></bdi>',
                  "CC BY-SA 4.0"),
    "69021699": ('<a href="//commons.wikimedia.org/wiki/User:Grendelkhan" title="User:Grendelkhan">'
                 'Grendelkhan</a>', "CC BY-SA 3.0"),
    "72183876": ('<div class="fn value">\nMuseum of Veterinary Anatomy FMVZ USP</div>', "CC BY-SA 4.0"),
}


def commons_reply_with_metadata() -> bytes:
    data = json.loads((API / "commons.json").read_bytes())
    pages = data["query"]["pages"]
    for page_id, (artist, licence) in COMMONS_META.items():
        pages[page_id]["imageinfo"][0]["extmetadata"] = {
            "Artist": {"value": artist, "source": "commons-desc-page"},
            "LicenseShortName": {"value": licence, "source": "commons-desc-page", "hidden": ""}}
    pages["19002220"]["imageinfo"][0]["extmetadata"] = {"Artist": {"value": ["Barras"]},
                                                         "LicenseShortName": 7}
    return json.dumps(data).encode()


def test_commons_licence_and_creator_come_from_extmetadata(monkeypatch):
    served = fake_http([])

    def get(url, *args, **kwargs):
        if "commons.wikimedia.org/w/api.php" in url:
            return commons_reply_with_metadata(), "application/json"
        return served(url, *args, **kwargs)
    monkeypatch.setattr(sources, "http_get", get)
    run = run_tool("fetch", {"query": "golden retriever", "source": "commons", "n": 4}, MemoryStore())
    found = aligned(run)
    assert [(s["creator"], s["license"]) for s in found[:4]] == [
        ("Dietmar Rabich", "CC BY-SA 4.0"), ("Grendelkhan", "CC BY-SA 3.0"), (None, None),
        ("Museum of Veterinary Anatomy FMVZ USP", "CC BY-SA 4.0")]
    assert found[2]["page"] == "https://commons.wikimedia.org/wiki/File:A_Golden_Retriever-9_(Barras).JPG"
    assert found[2]["title"] == "A Golden Retriever-9 (Barras).JPG"


@pytest.mark.parametrize("value,text", [
    ("<b>Tom &amp; Jerry</b>\n  Studio", "Tom & Jerry Studio"),
    ("CC BY-SA 4.0", "CC BY-SA 4.0"),
    ("<span></span>  ", None),
    (None, None),
    ({"value": "x"}, None),
])
def test_html_text(value, text):
    assert sources.html_text(value) == text


@pytest.mark.parametrize("code,version,name", [
    ("by-nc", "2.0", "CC BY-NC 2.0"), ("by", "4.0", "CC BY 4.0"), ("cc0", "1.0", "CC0 1.0"),
    ("pdm", "1.0", "Public Domain Mark 1.0"), ("by-sa", None, "CC BY-SA"), ("by", 2, "CC BY"),
    (None, "2.0", None), ("", "2.0", None), (["by"], "2.0", None),
])
def test_openverse_licence_names(code, version, name):
    assert sources.openverse_license(code, version) == name


def thumb_web(requested: list[str], gone: set[str]):
    """The fake web, where Openverse thumbnails are images and the links in `gone` are 404s."""
    served = fake_http(requested)

    def get(url, *args, **kwargs):
        if url in gone:
            requested.append(url)
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        if url.endswith("/thumb/"):
            requested.append(url)
            return (FIXTURES / "lincoln.png").read_bytes(), "image/png"
        return served(url, *args, **kwargs)
    return get


def test_url_is_the_link_that_delivered_the_bytes(monkeypatch):
    results = json.loads((API / "openverse.json").read_bytes())["results"]
    gone = {results[0]["url"], results[1]["url"], results[1]["thumbnail"]}  # 1: original gone; 2: both gone
    requested: list[str] = []
    monkeypatch.setattr(sources, "http_get", thumb_web(requested, gone))
    run = run_tool("fetch", {"query": "golden retriever", "source": "openverse", "n": 3}, MemoryStore())
    found = aligned(run)
    assert [o.key for o in run.result.outputs] == ["1", "3", "sheet"]  # candidate 2 was skipped
    assert [s and (s["url"], s["page"]) for s in found] == [
        (results[0]["thumbnail"], results[0]["foreign_landing_url"]),
        (results[2]["url"], results[2]["foreign_landing_url"]),
        None]
    assert requested[1:5] == [results[0]["url"], results[0]["thumbnail"],  # after the API call
                              results[1]["url"], results[1]["thumbnail"]]


def test_wiki_sources(web):
    run = run_tool("wiki", {"title": "Abraham Lincoln", "n": 2}, MemoryStore())
    pages = json.loads((API / "wiki.json").read_bytes())["query"]["pages"]
    found = aligned(run)
    assert found[0] == {"kind": "wikipedia", "url": pages["307"]["thumbnail"]["source"],
                        "page": "https://en.wikipedia.org/wiki/Abraham_Lincoln", "title": "Abraham Lincoln",
                        "license": None, "creator": None}
    assert found[1]["page"] == "https://en.wikipedia.org/wiki/Assassination_of_Abraham_Lincoln"
    assert found[2] is None


@pytest.mark.parametrize("lang,title,page", [
    ("en", "Abraham Lincoln", "https://en.wikipedia.org/wiki/Abraham_Lincoln"),
    ("de", "Dülmen (Stadt)", "https://de.wikipedia.org/wiki/D%C3%BClmen_(Stadt)"),
    ("en", "AC/DC", "https://en.wikipedia.org/wiki/AC/DC"),
    ("en", "Who's Afraid? 100% & more", "https://en.wikipedia.org/wiki/Who%27s_Afraid%3F_100%25_%26_more"),
    ("en", 42, None),
])
def test_wikipedia_page_links(lang, title, page):
    assert sources.wiki_page(lang, title) == page


def test_emoji_sources(monkeypatch):
    def get(url, *args, **kwargs):
        if url.endswith("/1f602.png"):
            return (FIXTURES / "emoji_joy.png").read_bytes(), "image/png"
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    monkeypatch.setattr(sources, "http_get", get)
    run = run_tool("emoji", {"emoji": ["notanemoji", "joy"]}, MemoryStore())
    assert aligned(run) == [{"kind": "twemoji", "url": sources.TWEMOJI_URL.format("1f602"), "page": None,
                             "title": "😂", "license": "CC-BY 4.0",
                             "creator": "Twitter/X and Twemoji contributors"}]


def test_template_sources(web):
    run = run_tool("template", {"name": "drake", "n": 2}, MemoryStore())
    found = aligned(run)
    assert found == [
        {**NOTHING, "kind": "imgflip", "url": "https://i.imgflip.com/1iruch.jpg", "title": "Drake Blank"},
        {**NOTHING, "kind": "imgflip", "url": "https://i.imgflip.com/30b1gx.jpg",
         "title": "Drake Hotline Bling"},
        None]
    assert run_tool("template", {"list_all": True}, MemoryStore()).result.data == {"sources": []}


def test_url_sources(web):
    run = run_tool("fetch", {"query": "https://example.org/pic.png"}, MemoryStore())
    assert aligned(run) == [{**NOTHING, "kind": "url", "url": "https://example.org/pic.png"}]
    run = run_tool("fetch", {"query": "https://example.org/article.html"}, MemoryStore())
    assert aligned(run) == [{**NOTHING, "kind": "url", "url": "https://example.org/images/lincoln.png",
                             "page": "https://example.org/article.html"}]


def test_clipboard_sources(monkeypatch, web):
    monkeypatch.setattr(sources, "read_clipboard", lambda: ((FIXTURES / "lincoln.png").read_bytes(), None))
    run = run_tool("fetch", {"clipboard": True}, MemoryStore())
    assert aligned(run) == [{**NOTHING, "kind": "clipboard"}]
    assert web == []
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "https://example.org/article.html"))
    run = run_tool("fetch", {"clipboard": True}, MemoryStore())
    assert aligned(run) == [{**NOTHING, "kind": "clipboard", "url": "https://example.org/images/lincoln.png",
                             "page": "https://example.org/article.html"}]


EVIL = "cat\x1b[2K\rFAKE LINE\x07\x9b"


def test_remote_values_are_scrubbed_strings_or_none(monkeypatch):
    openverse = {"results": [
        {"url": "https://e.org/a.png", "title": EVIL, "license": "by-sa\x1b", "license_version": "4.0",
         "creator": {"name": "x"}, "foreign_landing_url": ["https://e.org/"]},
        {"url": "https://e.org/b.png", "title": "  ", "license": "cc0", "license_version": "1.0",
         "creator": "\x1b\x07", "foreign_landing_url": "https://e.org/b\x1b[2K.html"}]}

    def get(url, *args, **kwargs):
        if "api.openverse.org" in url:
            return json.dumps(openverse).encode(), "application/json"
        if url.endswith(".html"):
            return f'<meta property="og:image" content="/pic{EVIL}.png">'.encode(), "text/html"
        return (FIXTURES / "lincoln.png").read_bytes(), "image/png"
    monkeypatch.setattr(sources, "http_get", get)
    run = run_tool("fetch", {"query": "cats", "source": "openverse", "n": 2}, MemoryStore())
    assert aligned(run)[:2] == [  # b's creator was only control characters: None, not blank
        {"kind": "openverse", "url": "https://e.org/a.png", "page": None, "title": "cat [2K FAKE LINE",
         "license": "CC BY-SA  4.0", "creator": None},
        {"kind": "openverse", "url": "https://e.org/b.png", "page": "https://e.org/b [2K.html", "title": None,
         "license": "CC0 1.0", "creator": None}]
    run = run_tool("fetch", {"query": "https://e.org/page.html"}, MemoryStore())
    assert aligned(run) == [{**NOTHING, "kind": "url", "url": "https://e.org/piccat [2KFAKE LINE  .png",
                             "page": "https://e.org/page.html"}]  # (urljoin drops the carriage return)


def test_lone_surrogates_become_replacement_characters(monkeypatch):
    # json.loads turns a "\ud800" escape into a lone surrogate, which UTF-8 can't encode: the CLI's print
    # and the server's model_dump_json raised UnicodeEncodeError on it. Each one becomes U+FFFD.
    openverse = {"results": [{"url": "https://e.org/a.png", "title": "cat \ud800", "license": "by",
                              "license_version": "4.0", "creator": "\ud800bob\udfff",
                              "foreign_landing_url": "https://e.org/a"}]}

    def get(url, *args, **kwargs):
        if "api.openverse.org" in url:
            return json.dumps(openverse).encode(), "application/json"  # ASCII: the "\\ud800" escapes
        return (FIXTURES / "lincoln.png").read_bytes(), "image/png"
    monkeypatch.setattr(sources, "http_get", get)
    run = run_tool("fetch", {"query": "cats", "source": "openverse", "n": 1}, MemoryStore())
    assert aligned(run) == [{"kind": "openverse", "url": "https://e.org/a.png", "page": "https://e.org/a",
                             "title": "cat �", "license": "CC BY 4.0", "creator": "�bob�"}]
    assert run.result.outputs[0].caption.endswith(") cat �  [openverse, BY 4.0, by �bob�]")
    for text in [*run.result.lines, *(o.caption for o in run.result.outputs)]:
        text.encode("utf-8")  # what the CLI prints
