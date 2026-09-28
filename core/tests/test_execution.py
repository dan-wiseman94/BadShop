"""The tool-call boundary (ToolCall -> execute_call -> ToolOutcome) and the private-address URL policy."""

import hashlib
import io
import json
import pickle
import socket
import threading
import urllib.parse
from pathlib import Path

import numpy as np
import pytest
from PIL import EpsImagePlugin, Image

import badshop
from badshop.engine import assets, basic, sources
from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Params
from badshop.session import netpolicy
from badshop.session.execution import (
    CRASH_HINT, STOPPED, BytesStore, Executor, InProcessExecutor, OutputRecord, ToolCall, ToolOutcome,
    cache_key, execute_call, json_safe,
)
from badshop.tools.registry import REGISTRY, ToolSpec
from conftest import FIXTURES
from localweb import response, serve
from test_downloads import pixel_bomb_png

LINCOLN = (FIXTURES / "lincoln.png").read_bytes()
LINCOLN_ID = hashlib.sha256(LINCOLN).hexdigest()


def png(size=(40, 30), color="red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


# --- the private-address policy (carry-forward SEC-S2) ---

@pytest.mark.parametrize("url", [
    "http://8.8.8.8/x.png", "https://93.184.215.14:8443/a/b.jpg", "http://[2001:4860:4860::8888]/x",
])
def test_public_addresses_pass(url):
    assert netpolicy.refuse_private(url) is None  # numeric hosts: no DNS lookup, so this runs offline


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "https://localhost:8000/x.png", "http://LOCALHOST/", "http://10.0.0.5/",
    "http://172.16.3.4/", "http://192.168.1.1/router.png", "http://169.254.169.254/latest/meta-data/",
    "http://100.100.100.100/", "http://0.0.0.0:8080/", "http://224.0.0.1/", "http://240.0.0.1/",
    "http://[::1]:8080/", "http://[::]/", "http://[fe80::1]/", "http://[fc00::1]/", "http://[fec0::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::c0a8:101]/",
    # urllib percent-decodes the host (urlsplit does not): both of these connect to 127.0.0.1
    "http://%31%32%37.0.0.1/", "http://127.0.0.1%3A8080/x",
    # urllib can't connect to these (it reads "pw@127.0.0.1" as a port, "x.org@127.0.0.1" as a host);
    # urlsplit reads 127.0.0.1, so they are refused whichever parser a future urllib follows
    "http://user:pw@127.0.0.1/", "http://x.org@127.0.0.1/",
])
def test_local_and_private_addresses_are_refused(url):
    with pytest.raises(EngineError, match="this computer or the local network") as e:
        netpolicy.refuse_private(url)
    assert "import the file" in e.value.hint


@pytest.mark.parametrize("url", [
    "http://2130706433/", "http://0x7f.1/", "http://127.1/", "http://017700000001/",
])
def test_odd_spellings_of_loopback_are_refused_wherever_they_resolve(url):
    try:
        socket.getaddrinfo(urllib.parse.urlsplit(url).hostname, None)
    except OSError:  # this resolver can't read the spelling, so urllib can't connect to it either
        assert netpolicy.refuse_private(url) is None
        return
    with pytest.raises(EngineError, match="local network"):
        netpolicy.refuse_private(url)


def test_the_resolved_addresses_decide(monkeypatch):
    asked = []

    def resolve(host, port, family=0, type=0, proto=0, flags=0):
        asked.append(host)
        addresses = {"public.example": ["93.184.215.14"], "mixed.example": ["93.184.215.14", "10.1.2.3"],
                     "v6.example": ["2001:db8::1"]}
        if host not in addresses:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0))
                for a in addresses[host]]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert netpolicy.refuse_private("https://public.example/cat.jpg") is None
    with pytest.raises(EngineError, match="local network"):  # one private address is enough to refuse
        netpolicy.refuse_private("https://mixed.example/cat.jpg")
    with pytest.raises(EngineError, match="local network"):  # the documentation range is not public
        netpolicy.refuse_private("https://v6.example/cat.jpg")
    # a name that doesn't resolve passes: the request itself fails the same way
    assert netpolicy.refuse_private("https://nothing.invalid/cat.jpg") is None
    # both readings of the host reach the resolver: urlsplit's, and urllib's (percent-decoded, no port)
    assert netpolicy.refuse_private("https://%70ublic.example:8443/x") is None
    assert asked == ["public.example", "mixed.example", "v6.example", "nothing.invalid",
                     "%70ublic.example", "public.example"]


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "data:image/png;base64,iVBORw0KGgo=", "http:///x.png", "no scheme at all",
    "http://[::1/",  # an unclosed bracket: no resolver reads that host
])
def test_links_urllib_cannot_connect_to_are_left_to_urllib(url):
    assert netpolicy.refuse_private(url) is None


def test_trusted_links_skip_only_their_exact_first_hop():
    typed = "http://127.0.0.1:9/cat.png"
    assert netpolicy.refuse_private(typed, frozenset({typed})) is None
    with pytest.raises(EngineError):
        netpolicy.refuse_private("http://127.0.0.1:9/other.png", frozenset({typed}))
    policy = netpolicy.policy_for(frozenset({typed}))
    assert policy(typed) is None
    with pytest.raises(EngineError):
        policy("http://127.0.0.1:9/")


def test_guarded_installs_the_policy_and_restores_the_previous_one(monkeypatch):
    def before(url):
        return None
    monkeypatch.setattr(assets, "URL_POLICY", before)
    with netpolicy.guarded(frozenset({"http://127.0.0.1/typed.png"})):
        inner = assets.URL_POLICY
        assert inner is not before
        inner("http://127.0.0.1/typed.png")
        with pytest.raises(EngineError):
            inner("http://127.0.0.1/other.png")
        with netpolicy.guarded():
            assert assets.URL_POLICY is not inner
        assert assets.URL_POLICY is inner
    assert assets.URL_POLICY is before
    with pytest.raises(RuntimeError):
        with netpolicy.guarded():
            raise RuntimeError("a tool failed")
    assert assets.URL_POLICY is before


def site(requested: list[str]):
    """A local web server's reply: an image, a page advertising it, and a redirect to it."""
    def reply(conn, path):
        requested.append(path)
        if path == "/pic.png":
            conn.sendall(response(png(), headers={"Content-Type": "image/png"}))
        elif path == "/page.html":
            html = b'<html><head><meta property="og:image" content="/pic.png"></head></html>'
            conn.sendall(response(html, headers={"Content-Type": "text/html"}))
        elif path == "/start":
            conn.sendall(response(status="302 Found", headers={"Location": "/pic.png"}))
        else:
            conn.sendall(response(b"no", status="404 Not Found"))
    return reply


def test_guarded_downloads_check_the_first_url_and_every_redirect_hop():
    requested = []
    with serve(site(requested)) as base:
        with netpolicy.guarded():
            with pytest.raises(EngineError, match="local network"):
                assets.http_get(base + "/pic.png")
        assert requested == []  # refused before connecting
        with netpolicy.guarded(frozenset({base + "/start"})):
            with pytest.raises(EngineError, match="local network"):  # the typed link, then a hop it chose
                assets.http_get(base + "/start")
        assert requested == ["/start"]
        with netpolicy.guarded(frozenset({base + "/pic.png"})):
            assert assets.http_get(base + "/pic.png") == (png(), "image/png")
    assert assets.URL_POLICY is None


def test_a_percent_encoded_local_host_is_refused():
    requested = []
    with serve(site(requested)) as base:
        encoded = base.replace("127.0.0.1", "%31%32%37.0.0.1") + "/pic.png"
        assert assets.http_get(encoded) == (png(), "image/png")  # urllib really connects to 127.0.0.1
        with netpolicy.guarded():
            with pytest.raises(EngineError, match="local network"):
                assets.http_get(encoded)
    assert requested == ["/pic.png"]


def test_typed_urls_are_a_users_fetch_links_only():
    link = "http://192.168.1.20/cat.png"
    assert netpolicy.typed_urls("fetch", {"query": link}, "user") == frozenset({link})
    assert netpolicy.typed_urls("fetch", {"query": link}, "agent:fake") == frozenset()
    assert netpolicy.typed_urls("fetch", {"query": link}, "cli:claude") == frozenset()
    assert netpolicy.typed_urls("fetch", {"query": "lincoln portrait"}, "user") == frozenset()
    assert netpolicy.typed_urls("fetch", {"query": None, "clipboard": True}, "user") == frozenset()
    assert netpolicy.typed_urls("wiki", {"title": link}, "user") == frozenset()


# --- the tool-call boundary ---

class NoParams(Params):
    pass


@pytest.fixture
def scratch_tool(monkeypatch):
    """Register a throwaway tool for one test; monkeypatch removes it again."""
    def add(name, run):
        monkeypatch.setitem(REGISTRY, name, ToolSpec(
            name=name, params=NoParams, run=run, summary="a test tool",
            description="a tool that exists only in these tests", category="inspect"))
    return add


def test_execute_call_runs_a_tool_on_artifact_bytes():
    call = ToolCall("prep", {"image": LINCOLN_ID, "max": 300}, {LINCOLN_ID: LINCOLN}, stem="lincoln")
    out = execute_call(call)
    expected = basic.prep(basic.PrepParams(image=LINCOLN_ID, max=300), load_image(LINCOLN))
    assert out.ok and not out.crashed and out.error_message is None and out.error_hint is None
    assert [r.key for r in out.outputs] == ["work", "grid"]
    # name hints stay as the tool gave them: the session turns them into labels
    assert [r.name_hint for r in out.outputs] == ["{stem}_work.png", "{stem}_work_grid.png"]
    assert [r.data for r in out.outputs] == [o.encode() for o in expected.outputs]  # the engine's own bytes
    assert out.lines == expected.lines == ["size: 228x300"]
    assert out.data == {}


def test_tool_data_is_made_json_safe(scratch_tool):
    data = {"box": (1, 2, 3, 4), "where": Path("a") / "b.png", "n": 1.5}
    scratch_tool("_data", lambda p, s: EngineResult(data=data))
    out = execute_call(ToolCall("_data", {}, {}, stem=""))
    assert out.ok and out.data == {"box": [1, 2, 3, 4], "where": str(Path("a") / "b.png"), "n": 1.5}
    assert json.loads(json.dumps(out.data)) == out.data


def test_non_finite_floats_in_tool_data_become_null(scratch_tool):
    """Python's json writes NaN and infinity as bare NaN/Infinity, which JavaScript's JSON.parse refuses:
    one in a tool's data would make every reply carrying the step unreadable in the shell (ruling R4)."""
    data = {"score": float("nan"), "ratio": float("inf"), "floor": -float("inf"), "coverage": 0.5,
            "boxes": [(1.5, float("nan"))], "deep": {"list": [np.float64("inf"), 2]}, "text": "NaN"}
    scratch_tool("_nan", lambda p, s: EngineResult(data=data))
    out = execute_call(ToolCall("_nan", {}, {}, stem=""))
    expected = {"score": None, "ratio": None, "floor": None, "coverage": 0.5,
                "boxes": [[1.5, None]], "deep": {"list": [None, 2]}, "text": "NaN"}  # a string stays a string
    assert out.ok and out.data == expected
    strict = json.dumps(out.data, allow_nan=False)  # raises ValueError if a NaN or an infinity is left
    assert json.loads(strict) == expected
    assert json_safe(data) == expected  # the same coercion, callable on its own
    assert json_safe({"n": -0.0, "tiny": 5e-324, "big": 10**30}) == {"n": -0.0, "tiny": 5e-324, "big": 10**30}


@pytest.mark.parametrize("tool, params, inputs, message, hint", [
    ("prep", {"image": LINCOLN_ID, "max": "big"}, {LINCOLN_ID: LINCOLN}, "bad parameters for prep", "max"),
    ("nope", {}, {}, "unknown tool 'nope'", "tools: "),
    ("info", {"image": "f" * 64}, {LINCOLN_ID: LINCOLN}, f"no such artifact: {'f' * 64}", "a3f9c1d2"),
    ("info", {"image": LINCOLN_ID}, {LINCOLN_ID: b"not an image"}, "can't be read as an image", "import"),
    ("cutout", {"image": LINCOLN_ID, "box": [5000, 5000, 6000, 6000], "no_ai": True}, {LINCOLN_ID: LINCOLN},
     "is empty or lies outside", "boxes are X1 Y1 X2 Y2"),
])
def test_engine_errors_are_clean_failures(tool, params, inputs, message, hint):
    out = execute_call(ToolCall(tool, params, inputs, stem="lincoln"))
    assert not out.ok and not out.crashed and out.outputs == [] and out.lines == [] and out.data == {}
    assert message in out.error_message and hint in out.error_hint


def test_inputs_never_reach_risky_decoders(monkeypatch):
    opened = []
    monkeypatch.setattr(EpsImagePlugin.EpsImageFile, "_open", lambda self: opened.append(self))
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"
    out = execute_call(ToolCall("info", {"image": LINCOLN_ID}, {LINCOLN_ID: eps}, stem=""))
    assert not out.ok and not out.crashed and "can't be read as an image" in out.error_message
    assert opened == []  # the EPS decoder (which runs Ghostscript) was never tried


def test_a_pixel_bomb_input_is_a_clean_failure():
    bomb = pixel_bomb_png(20000, 10000)
    out = execute_call(ToolCall("info", {"image": LINCOLN_ID}, {LINCOLN_ID: bomb}, stem=""))
    assert not out.ok and not out.crashed and "can't be read as an image" in out.error_message


def test_any_decoder_error_is_a_clean_failure():
    """Hostile bytes can make a decoder raise almost anything, not only OSError: Pillow reads a PNG whose
    header chunk is too short as a ValueError. That is a bad input, not a bug in badshop."""
    short_header = bytearray(png())
    short_header[8:12] = (5).to_bytes(4, "big")  # the IHDR chunk's length field: 5 bytes, not 13
    out = execute_call(ToolCall("info", {"image": LINCOLN_ID}, {LINCOLN_ID: bytes(short_header)}, stem=""))
    assert not out.ok and not out.crashed and out.error_hint == "import the picture again"
    assert out.error_message.startswith(f"artifact {LINCOLN_ID[:8]} can't be read as an image (")
    # Pillow's "cannot identify image file <_io.BytesIO object at 0x...>" says nothing, so it is left out
    unknown = execute_call(ToolCall("info", {"image": LINCOLN_ID}, {LINCOLN_ID: b"not an image"}, stem=""))
    assert unknown.error_message == f"artifact {LINCOLN_ID[:8]} can't be read as an image"


def test_a_crash_is_a_clean_failure_that_keeps_nothing(scratch_tool):
    def boom(p, s):
        raise ValueError("boom")
    scratch_tool("_boom", boom)
    out = execute_call(ToolCall("_boom", {}, {}, stem=""))
    assert (out.ok, out.crashed) == (False, True)
    assert out.error_message == "the tool crashed (ValueError: boom)" and out.error_hint == CRASH_HINT
    # a failure while encoding: the first output was already stored, and is dropped with the rest
    scratch_tool("_badjpeg", lambda p, s: EngineResult(outputs=[
        Output("fine", Image.new("RGB", (4, 4)), "fine.png"),
        Output("bad", Image.new("RGBA", (4, 4)), "bad.jpg", fmt="JPEG"),  # RGBA can't be a JPEG
    ], lines=["made two"]))
    out = execute_call(ToolCall("_badjpeg", {}, {}, stem=""))
    assert out.crashed and out.outputs == [] and out.lines == []
    assert out.error_message.startswith("the tool crashed (OSError: ")


def test_the_call_runs_as_validated_whoever_proposed_it(monkeypatch):
    """The actor check belongs to the session (runner.validate with the actor); a ToolCall is already
    approved, so a user-only field such as fetch's clipboard is accepted here."""
    monkeypatch.setattr(sources, "read_clipboard", lambda: (LINCOLN, None))
    out = execute_call(ToolCall("fetch", {"clipboard": True}, {}, stem=""))
    assert out.ok and [r.key for r in out.outputs] == ["fetched"]
    with Image.open(io.BytesIO(out.outputs[0].data)) as im:
        assert im.size == (457, 600)


def test_network_tools_run_under_the_policy():
    requested = []
    with serve(site(requested)) as base:
        link, page = base + "/pic.png", base + "/page.html"
        refused = execute_call(ToolCall("fetch", {"query": link}, {}, stem=""))
        assert not refused.ok and not refused.crashed and "local network" in refused.error_message
        assert requested == []
        typed = execute_call(ToolCall("fetch", {"query": link}, {}, stem="", trusted_urls=frozenset({link})))
        assert typed.ok and [r.key for r in typed.outputs] == ["fetched"]
        # a page the user typed may not steer the download into the local network through its og:image
        steered = execute_call(ToolCall("fetch", {"query": page}, {}, stem="",
                                        trusted_urls=frozenset({page})))
        assert not steered.ok and "local network" in steered.error_message
        unguarded = execute_call(ToolCall("fetch", {"query": page}, {}, stem="", guard_network=False))
        assert unguarded.ok and [r.key for r in unguarded.outputs] == ["fetched"]
        assert requested == ["/pic.png", "/page.html", "/page.html", "/pic.png"]
    assert assets.URL_POLICY is None  # every call put the previous policy back


def test_bytes_store_decodes_fresh_copies_and_keeps_encoded_outputs():
    red = png()
    rid = hashlib.sha256(red).hexdigest()
    store = BytesStore({rid: red})
    first = store.load(rid)
    first.paste((0, 0, 255), (0, 0, 10, 10))  # a tool may draw on what it loaded
    assert store.load(rid).getpixel((0, 0)) == (255, 0, 0)
    work = Output("work", first, "{stem}_work.png", caption="(40x30)")
    assert store.put(work, "lincoln") == "out:0"
    assert store.put(Output("grid", first, "{stem}_grid.png"), "lincoln") == "out:1"
    assert store.outputs[0] == OutputRecord("work", work.encode(), "{stem}_work.png", "(40x30)")
    assert [r.key for r in store.outputs] == ["work", "grid"]
    with pytest.raises(EngineError, match="export runs in the session"):
        store.export(rid, "keeper")


def test_calls_and_outcomes_cross_a_process_boundary():
    # The worker's Pipe pickles both ways; these objects are this test's own, never untrusted data.
    call = ToolCall("prep", {"image": LINCOLN_ID}, {LINCOLN_ID: LINCOLN}, stem="lincoln",
                    trusted_urls=frozenset({"http://x.org/a.png"}), guard_network=False)
    assert pickle.loads(pickle.dumps(call)) == call
    out = execute_call(call)
    back = pickle.loads(pickle.dumps(out))
    assert back == out and back.outputs[0].data == out.outputs[0].data
    failed = ToolOutcome(ok=False, error_message="m", error_hint="h", crashed=True)
    assert pickle.loads(pickle.dumps(failed)) == failed
    assert ToolOutcome(ok=True).outputs is not ToolOutcome(ok=True).outputs  # no shared mutable defaults


def test_cache_key(monkeypatch):
    key = cache_key("paste", {"base": "a" * 64, "scale": 1.1, "at": [1, 2]})
    blob = json.dumps({"engine": badshop.__version__, "tool": "paste",
                       "params": {"at": [1, 2], "base": "a" * 64, "scale": 1.1}},
                      separators=(",", ":"), sort_keys=True)
    assert key == hashlib.sha256(blob.encode()).hexdigest() and len(key) == 64
    assert cache_key("paste", {"at": [1, 2], "scale": 1.1, "base": "a" * 64}) == key  # any key order
    assert cache_key("paste", {"base": "b" * 64, "scale": 1.1, "at": [1, 2]}) != key  # other input bytes
    assert cache_key("warp", {"base": "a" * 64, "scale": 1.1, "at": [1, 2]}) != key
    monkeypatch.setattr(badshop, "__version__", "99.0.0")
    assert cache_key("paste", {"base": "a" * 64, "scale": 1.1, "at": [1, 2]}) != key  # a new engine re-runs


def test_in_process_executor():
    ex = InProcessExecutor()
    assert isinstance(ex, Executor)
    call = ToolCall("info", {"image": LINCOLN_ID}, {LINCOLN_ID: LINCOLN}, stem="lincoln")
    out = ex.run(call)
    assert out == execute_call(call) and out.data == {"width": 457, "height": 600}
    assert out.lines == [f"{LINCOLN_ID}: 457x600"]
    ex.cancel()
    ex.close()


def test_a_call_stopped_before_it_begins_never_runs(scratch_tool):
    """A call's own cancel event (Task 11's Stop hands one to each step) set before the call begins: the
    tool never runs, and the outcome is the stopped message, not a crash. An event that isn't set changes
    nothing."""
    ran = []
    scratch_tool("_count", lambda p, s: ran.append(1) or EngineResult(lines=["counted"]))
    ex, stop = InProcessExecutor(), threading.Event()
    assert ex.run(ToolCall("_count", {}, {}, stem=""), stop).lines == ["counted"] and ran == [1]
    stop.set()
    out = ex.run(ToolCall("_count", {}, {}, stem=""), cancel=stop)
    assert (out.ok, out.crashed, out.error_message, out.error_hint) == (False, False, STOPPED, None)
    assert STOPPED == "stopped by the user" and out.outputs == [] and ran == [1]
