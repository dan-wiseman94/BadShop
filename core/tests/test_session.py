import io
import json
import os
import threading

import pytest
from PIL import Image

from badshop import files
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.sources import TWEMOJI_URL
from badshop.engine.types import Params
from badshop.session.artifacts import ArtifactStore, describe, short
from badshop.session.execution import (CRASH_HINT, STOPPED, InProcessExecutor, OutputRecord, ToolCall,
                                       ToolOutcome, cache_key)
from badshop.session.models import Message, Part, SessionData
from badshop.session.session import Session, label_for, result_text
from badshop.tools.registry import REGISTRY, ToolSpec
from conftest import FIXTURES

LINCOLN = (FIXTURES / "lincoln.png").read_bytes()
TRUMP = (FIXTURES / "trump.png").read_bytes()


def png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class ScriptedExecutor:
    """An Executor that records every call and answers with canned outcomes; no tool runs.
    An exception in the script is raised from run(), like a broken executor would."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[ToolCall] = []
        self.stops: list[threading.Event | None] = []  # the cancel event each call came with

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome:
        self.calls.append(call)
        self.stops.append(cancel)
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def events():
    return []


@pytest.fixture
def session(tmp_path, events):
    return Session.new("test", output_dir=tmp_path / "out", emit=lambda e, p: events.append((e, p)))


def test_new_session_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "pics"))
    s = Session.new()
    assert s.data.name == "Untitled" and s.data.approval_mode == "ask_changes" and s.data.steps == []
    assert isinstance(s.executor, InProcessExecutor) and s.output_dir == tmp_path / "pics"
    assert s.changes == [] and s.last_output() is None and s.summary() == ""
    assert s.data.artifacts is s.artifacts.meta  # snapshots and project files see every artifact
    dumped = json.loads(s.data.model_dump_json(by_alias=True))
    assert dumped["schema"] == 2 and dumped["name"] == "Untitled"


def test_propose_resolves_refs_to_full_ids(session, events):
    work = session.import_image(LINCOLN, "lincoln")
    step = session.propose("prep", {"image": work.id[:6].upper()}, "agent:fake", reason="make a copy")
    assert (step.id, step.index, step.status, step.actor, step.reason) == ("s1", 1, "proposed", "agent:fake",
                                                                            "make a copy")
    assert step.params == {"image": work.id, "max": 1000}  # full id, defaults filled in, JSON-safe
    assert [e for e, _ in events] == ["step.proposed"]
    assert events[0][1] == {"step": step.model_dump(mode="json"), "artifacts": []}


def test_refs_never_reach_the_disk(session, tmp_path):
    (tmp_path / "secret.png").write_bytes(LINCOLN)
    for actor in ("agent:fake", "cli:claude", "user"):  # paths enter only through import, whoever asks
        with pytest.raises(EngineError, match="no such artifact"):
            session.propose("view", {"image": str(tmp_path / "secret.png")}, actor)
    with pytest.raises(EngineError, match="can only be set by the user"):
        session.propose("fetch", {"clipboard": True}, "agent:fake")
    with pytest.raises(EngineError, match="bad parameters for prep"):
        session.propose("prep", {"image": "x", "bogus": 1}, "user")
    assert session.data.steps == []


def test_run_turns_outputs_into_artifacts(session, events):
    work = session.import_image(LINCOLN, "lincoln")
    step = session.run_tool("prep", {"image": work.id, "max": 300}, "user")
    assert step.status == "done" and step.error is None and len(step.outputs) == 2
    grid_id = step.outputs[1]
    work2, grid = (session.artifacts.meta[i] for i in step.outputs)
    assert (work2.label, grid.label) == ("lincoln_work", "lincoln_work_grid")
    assert work2.produced_by == grid.produced_by == step.id and (grid.width, grid.height) == (228, 300)
    assert step.result_text == f"work: {describe(work2)}\ngrid: {describe(grid)}\nsize: 228x300"
    assert step.cache_key == cache_key("prep", step.params)
    assert step.started_at <= step.finished_at
    assert [e for e, _ in events] == ["step.proposed", "step.started", "step.finished"]
    assert events[1][1]["step"]["status"] == "running"
    assert events[2][1]["artifacts"] == [work2.model_dump(mode="json"), grid.model_dump(mode="json")]
    json.dumps([p for _, p in events])  # every payload goes over the wire as is
    assert session.last_output() == grid_id


def test_failed_step_has_clean_error(session, events):
    work = session.import_image(LINCOLN, "lincoln")
    step = session.run_tool("cutout", {"image": work.id, "box": [900, 900, 950, 950], "no_ai": True}, "agent:fake")
    assert step.status == "error" and step.outputs == [] and step.data is None
    assert step.error.message == "box (900, 900, 950, 950) is empty or lies outside the 457x600 image"
    assert step.result_text == f"error: {step.error.message}\nhint: {step.error.hint}"
    assert step.result_text.startswith("error: box") and "\nhint: boxes are X1 Y1 X2 Y2" in step.result_text
    assert [e for e, _ in events] == ["step.proposed", "step.started", "step.failed"]
    assert session.last_output() is None  # the import's note only: the agent's own step writes none
    assert session.changes == [f"the user added image {short(work.id)} (lincoln_work)"]


def test_identical_outputs_are_one_artifact_that_keeps_its_first_producer(session, events):
    work = session.import_image(LINCOLN, "lincoln")
    first = session.run_tool("filter", {"image": work.id, "names": ["sepia"]}, "user")
    before = set(session.artifacts.ids())
    second = session.run_tool("filter", {"image": work.id, "names": ["sepia"]}, "agent:fake")
    assert second.status == "done" and second.outputs == first.outputs
    assert set(session.artifacts.ids()) == before  # the same bytes were not stored twice
    meta = session.artifacts.meta[first.outputs[0]]
    assert meta.produced_by == first.id and meta.label == "lincoln_filter"
    finished = [p for e, p in events if e == "step.finished"]
    assert finished[-1]["artifacts"] == [meta.model_dump(mode="json")]  # produced_by still s1
    note = session.add_message("assistant", [Part(type="image", artifact_id=meta.id)], step_ids=[second.id])
    assert note.content[0].artifact_id == meta.id and note.step_ids == [second.id]
    # a step can give back an earlier step's pictures: prep of a prepped copy makes the same bytes
    small = session.run_tool("prep", {"image": work.id, "max": 300}, "user")
    again = session.run_tool("prep", {"image": small.outputs[0], "max": 300}, "agent:fake")
    assert again.status == "done" and again.outputs == small.outputs
    assert all(session.artifacts.meta[i].produced_by == small.id for i in again.outputs)


def test_run_with_user_edited_params(tmp_path):
    s = Session.new(output_dir=tmp_path)
    work = s.import_image(LINCOLN, "lincoln")
    step = s.propose("filter", {"image": work.id, "names": ["sepia"]}, "agent:fake")
    with pytest.raises(EngineError, match="bad parameters for filter"):
        s.run(step.id, {"image": work.id, "names": ["no-such-filter"]})
    assert step.status == "proposed" and step.params["names"] == ["sepia"] and not step.edited
    s.run(step.id, {"image": work.id[:8], "names": ["invert"]})
    assert step.status == "done" and step.edited and step.params == {"image": work.id, "names": ["invert"]}
    with pytest.raises(EngineError, match="s1 is done, so it can't run"):
        s.run(step.id)
    # the user may set user-only fields when they edit an agent's call; the agent may not
    ex = ScriptedExecutor(ToolOutcome(False, error_message="nothing on the clipboard"))
    s2 = Session.new(output_dir=tmp_path, executor=ex)
    fetch = s2.propose("fetch", {"query": "lincoln"}, "agent:fake")
    s2.run(fetch.id, {"clipboard": True})
    assert fetch.edited and ex.calls[0].params["clipboard"] is True and fetch.status == "error"


def test_reject(session, events):
    work = session.import_image(LINCOLN, "lincoln")
    step = session.propose("filter", {"image": work.id, "names": ["invert"]}, "agent:fake")
    session.reject(step.id, "too much")
    assert step.status == "rejected" and step.result_text == "rejected by user: too much"
    assert [e for e, _ in events] == ["step.proposed", "step.finished"]
    with pytest.raises(EngineError, match="rejected, so it can't run"):
        session.run(step.id)
    with pytest.raises(EngineError, match="can't be rejected"):
        session.reject(step.id)
    plain = session.propose("filter", {"image": work.id, "names": ["invert"]}, "agent:fake")
    assert session.reject(plain.id).result_text == "rejected by user"
    with pytest.raises(EngineError, match="no such step: s9"):
        session.reject("s9")


def test_tools_go_through_the_executor(tmp_path):
    ex = ScriptedExecutor(ToolOutcome(True, [OutputRecord("result", png(Image.new("RGB", (4, 4))), "result.png")],
                                      ["applied: invert"], {"note": 1}))
    s = Session.new(output_dir=tmp_path, executor=ex)
    work = s.import_image(LINCOLN, "lincoln")
    step = s.run_tool("filter", {"image": work.id, "names": ["invert"]}, "agent:fake")
    call = ex.calls[0]
    assert call.tool == "filter" and call.params == step.params and call.stem == "lincoln"
    assert call.inputs == {work.id: s.artifacts.data(work.id)}
    assert call.guard_network and call.trusted_urls == frozenset()
    assert step.data == {"note": 1} and s.artifacts.meta[step.outputs[0]].label == "lincoln_filter"


def test_fetched_pictures_enter_as_working_copies_with_provenance(tmp_path):
    url = "http://127.0.0.1:8000/big.png"
    big = png(Image.new("RGB", (1500, 1200), "red"))
    sheet = png(Image.new("RGB", (1200, 324), "gray"))
    src = {"kind": "url", "url": url, "page": None, "title": None, "license": None, "creator": None}
    fetched = ToolOutcome(True, [OutputRecord("1", big, "fetch/big_1.png", "(1500x1200) big"),
                                 OutputRecord("sheet", sheet, "fetch/big_sheet.png")],
                          ["source: test"], {"sources": [src, None], "hits": 1})
    ex = ScriptedExecutor(fetched, fetched)
    s = Session.new(output_dir=tmp_path, executor=ex)
    step = s.run_tool("fetch", {"query": url}, "user")
    assert ex.calls[0].trusted_urls == {url} and ex.calls[0].inputs == {}  # the user typed it
    work, sheet_meta = (s.artifacts.meta[i] for i in step.outputs)
    assert (work.width, work.height) == (1000, 800)
    assert work.label == ArtifactStore().import_image(big, "big_1")[0].label  # named as an import of big_1
    assert work.produced_by == step.id and work.source.kind == "url" and work.source.url == url
    original = s.artifacts.meta[work.original_id]
    assert s.artifacts.data(original.id) == big and original.produced_by == step.id
    assert sheet_meta.source is None and s.artifacts.data(sheet_meta.id) == sheet  # the tool's own render
    assert (sheet_meta.label, step.data) == ("big_sheet", {"hits": 1})  # sources live on the artifacts
    assert step.result_text == (f"1: {describe(work)} (1500x1200) big\n"
                                f"sheet: {describe(sheet_meta)}\nsource: test")
    s.run_tool("fetch", {"query": url}, "agent:fake")
    assert ex.calls[1].trusted_urls == frozenset()  # a model's link goes through the address policy


def test_a_small_fetched_png_is_one_artifact_that_still_records_its_step(tmp_path):
    face = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
    face.paste((255, 204, 77, 255), (8, 8, 64, 64))
    emoji = png(face)  # what emoji hands back: small, upright, transparent PNG, already a working copy
    src = {"kind": "twemoji", "url": TWEMOJI_URL.format("1f602"), "page": None, "title": "😂",
           "license": "CC-BY 4.0", "creator": "Twitter/X and Twemoji contributors"}
    ex = ScriptedExecutor(ToolOutcome(True, [OutputRecord("emoji", emoji, "fetch/emoji_1f602.png", "😂")],
                                      [], {"sources": [src]}))
    s = Session.new(output_dir=tmp_path, executor=ex)
    step = s.run_tool("emoji", {"emoji": ["joy"]}, "agent:fake")
    assert step.status == "done" and s.artifacts.ids() == step.outputs  # nothing stored beside it
    meta = s.artifacts.meta[step.outputs[0]]
    assert meta.produced_by == step.id and meta.original_id is None and s.artifacts.data(meta.id) == emoji
    assert (meta.label, meta.source.kind, meta.source.license) == ("emoji_1f602_work", "twemoji", "CC-BY 4.0")


def test_executor_failure_is_a_failed_step(tmp_path, events):
    ex = ScriptedExecutor(RuntimeError("pipe broke"),
                          ToolOutcome(False, error_message="the tool's process died (exit code -9)", crashed=True))
    s = Session.new(output_dir=tmp_path, executor=ex, emit=lambda e, p: events.append((e, p)))
    work = s.import_image(LINCOLN, "lincoln")
    step = s.run_tool("filter", {"image": work.id, "names": ["invert"]}, "user")
    assert step.status == "error" and step.finished_at is not None
    assert (step.error.message, step.error.hint) == ("the tool crashed (RuntimeError: pipe broke)", CRASH_HINT)
    died = s.run_tool("filter", {"image": work.id, "names": ["invert"]}, "user")
    assert died.result_text == "error: the tool's process died (exit code -9)"
    assert [e for e, _ in events][-1] == "step.failed"


def test_a_run_stopped_before_its_tool_begins_is_a_failed_step(tmp_path, events):
    """run() hands the caller's cancel event (Task 11's Stop) to the executor with the call. Set before the
    tool begins, the tool never runs and the step fails with the executor's stopped message; export, which
    runs in the session, is stopped the same way."""
    s = Session.new(output_dir=tmp_path / "out", emit=lambda e, p: events.append((e, p)))  # InProcessExecutor
    work = s.import_image(LINCOLN, "lincoln")
    before, stop = set(s.artifacts.ids()), threading.Event()
    stop.set()
    step = s.run(s.propose("filter", {"image": work.id, "names": ["invert"]}, "agent:fake").id, cancel=stop)
    assert step.status == "error" and step.outputs == [] and set(s.artifacts.ids()) == before
    assert (step.error.message, step.error.hint, step.result_text) == (STOPPED, None, f"error: {STOPPED}")
    assert [e for e, _ in events][-2:] == ["step.started", "step.failed"]
    export = s.run(s.propose("export", {"image": work.id}, "agent:fake").id, cancel=stop)
    assert export.status == "error" and export.error.message == STOPPED and not (tmp_path / "out").exists()
    ex = ScriptedExecutor(ToolOutcome(True), ToolOutcome(True))
    s.executor, mine = ex, threading.Event()
    s.run_tool("info", {"image": work.id}, "user")
    s.run(s.propose("info", {"image": work.id}, "agent:fake").id, cancel=mine)
    assert ex.stops == [None, mine]  # each call carries its own caller's event, or none


def test_export_writes_bytes_unchanged_and_never_overwrites(session, tmp_path):
    work = session.import_image(LINCOLN, "lincoln")
    first = session.export(work.id[:8])
    assert first == tmp_path / "out" / f"{work.label}.png" and first.read_bytes() == session.artifacts.data(work.id)
    assert session.export(work.id) == tmp_path / "out" / f"{work.label}_2.png"
    assert session.export(work.id, "my.meme") == tmp_path / "out" / "my.meme.png"
    for bad in ("../escape", "a/b", "..", ""):
        with pytest.raises(EngineError, match="bad file name"):
            session.export(work.id, bad)
    with pytest.raises(EngineError, match="no such artifact"):
        session.export("0123456789")
    saved = session.run_tool("save", {"image": work.id}, "user")  # a JPEG artifact keeps its format
    assert session.export(saved.outputs[0]).suffix == ".jpg"
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        [f"{work.label}.png", f"{work.label}_2.png", "my.meme.png", "lincoln.jpg"])


def test_export_never_loops_on_a_name_it_cannot_take(session, tmp_path, monkeypatch):
    work = session.import_image(LINCOLN, "lincoln")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(tmp_path / "gone" / "x.png", out / f"{work.label}.png")  # a link to a deleted file
    with pytest.raises(EngineError, match=f"can't write {work.label}.png: a broken link with that name") as e:
        session.export(work.id)
    assert "remove it" in e.value.hint and os.listdir(out) == [f"{work.label}.png"]
    real = files.final_path

    def raced(final_dir, stem, ext):  # another program saves under the name final_path just picked
        path = real(final_dir, stem, ext)
        if stem == "raced" and not (final_dir / "raced.png").exists():
            path.write_bytes(b"theirs")
        return path
    monkeypatch.setattr(files, "final_path", raced)
    assert session.export(work.id, "raced") == out / "raced_2.png"  # the next name, found by looking again
    assert (out / "raced.png").read_bytes() == b"theirs"  # theirs is never overwritten
    tries = []

    def always_taken(final_dir, stem, ext):
        path = final_dir / f"{stem}_{len(tries) + 1}{ext}"
        path.write_bytes(b"theirs")
        tries.append(path)
        return path
    monkeypatch.setattr(files, "final_path", always_taken)
    with pytest.raises(EngineError, match="no free file name for busy.png") as e:
        session.export(work.id, "busy")
    assert len(tries) == 100 and "another name" in e.value.hint


def test_export_tool_runs_in_the_session(tmp_path):
    ex = ScriptedExecutor()  # any call to it would fail the step
    s = Session.new(output_dir=tmp_path, executor=ex)
    work = s.import_image(LINCOLN, "lincoln")
    step = s.run_tool("export", {"image": work.id, "name": "keeper"}, "agent:fake")
    assert step.status == "done" and ex.calls == [] and step.outputs == []
    assert step.result_text == f"exported: {tmp_path / 'keeper.png'}"
    assert (tmp_path / "keeper.png").read_bytes() == s.artifacts.data(work.id)
    blocked = s.run_tool("export", {"image": work.id, "name": "keeper"}, "user")
    assert blocked.result_text == f"exported: {tmp_path / 'keeper_2.png'}"
    (tmp_path / "file").write_text("not a folder")
    s.output_dir = tmp_path / "file"
    failed = s.run_tool("export", {"image": work.id}, "user")
    assert failed.status == "error" and failed.error.message.startswith(f"can't write into {tmp_path / 'file'}")


class NoParams(Params):
    pass


def test_a_tool_that_writes_files_hands_back_strict_json_too(tmp_path, monkeypatch, events):
    """Tools that write files run in the session, not through execute_call, and their data gets the same
    coercion (ruling R4): no NaN or infinity reaches a step, an event or a JSON-RPC reply."""
    monkeypatch.setitem(REGISTRY, "_writer", ToolSpec(
        name="_writer", params=NoParams, summary="a test tool", category="finish", writes_files=True,
        description="a tool that exists only in these tests",
        run=lambda p, s: EngineResult(data={"ratio": float("nan"), "box": (1, 2), "text": "NaN"})))
    s = Session.new(output_dir=tmp_path, executor=ScriptedExecutor(), emit=lambda e, p: events.append((e, p)))
    step = s.run_tool("_writer", {}, "user")
    assert step.status == "done" and step.data == {"ratio": None, "box": [1, 2], "text": "NaN"}
    json.dumps([p for _, p in events], allow_nan=False)  # raises ValueError if a NaN is left


@pytest.mark.parametrize("hint, stem, tool, label", [
    ("result.png", "lincoln", "paste", "lincoln_paste"),
    ("result.png", "", "paste", "paste"),
    ("{stem}_work.png", "lincoln", "prep", "lincoln_work"),
    ("{stem}_work.png", "", "prep", "work"),
    ("final:{stem}_deepfried", "lincoln", "deepfry", "lincoln_deepfried"),
    ("final:my.meme", "lincoln", "save", "my.meme"),
    ("final:{stem}", "", "save", "save"),
    ("fetch/abraham_lincoln_1.jpg", "", "wiki", "abraham_lincoln_1"),
    ("fetch/emoji_1f602.png", "", "emoji", "emoji_1f602"),
])
def test_label_for(hint, stem, tool, label):
    assert label_for(OutputRecord("k", b"", hint), stem, tool) == label


def test_labels_follow_the_picture_a_chain_started_from(tmp_path):
    s = Session.new(output_dir=tmp_path)
    lincoln = s.import_image(LINCOLN, "lincoln")
    trump = s.import_image(TRUMP, "trump")
    work = s.run_tool("prep", {"image": lincoln.id, "max": 400}, "user").outputs[0]
    tinted = s.run_tool("filter", {"image": work, "names": ["sepia"]}, "user").outputs[0]
    head = s.run_tool("cutout", {"image": trump.id, "box": [100, 50, 300, 300], "oval": True}, "user").outputs[0]
    pasted = s.run_tool("paste", {"base": tinted, "piece": head, "fit_box": [120, 60, 320, 310]}, "user").outputs[0]
    fried = s.run_tool("deepfry", {"image": pasted, "level": 1}, "agent:fake").outputs[0]
    named = s.run_tool("save", {"image": fried, "name": "final_meme"}, "user").outputs[0]
    labels = [s.artifacts.meta[i].label for i in (work, tinted, head, pasted, fried, named)]
    assert labels == ["lincoln_work", "lincoln_filter", "trump_cutout", "lincoln_paste", "lincoln_deepfried",
                      "final_meme"]


def test_summary_changes_and_last_output(session):
    work = session.import_image(LINCOLN, "lincoln")
    prep = session.run_tool("prep", {"image": work.id, "max": 300}, "user")
    session.run_tool("cutout", {"image": work.id, "box": [900, 900, 950, 950], "no_ai": True}, "agent:fake")
    session.reject(session.propose("filter", {"image": work.id, "names": ["invert"]}, "agent:fake").id)
    waiting = session.propose("view", {"image": work.id}, "cli:claude")
    w, g = prep.outputs
    assert session.summary().splitlines() == [
        f"1. prep by user ✓ → {short(w)} (lincoln_work), {short(g)} (lincoln_work_grid)",
        "2. cutout by agent:fake ✗: box (900, 900, 950, 950) is empty or lies outside the 457x600 image",
        "3. filter by agent:fake rejected",
        "4. view by cli:claude proposed",
    ]
    assert session.last_output() == g
    assert session.take_changes() == [
        f"the user added image {short(work.id)} (lincoln_work)",
        f'the user ran step 1: prep {{"image": "{short(work.id)}", "max": 300}} → {short(w)} (lincoln_work), '
        f"{short(g)} (lincoln_work_grid)"]
    assert session.take_changes() == []
    session.run(waiting.id)
    edited = session.propose("filter", {"image": work.id, "names": ["invert"]}, "agent:fake")
    session.run(edited.id, {"image": work.id, "names": ["sepia"]})
    assert session.summary().splitlines()[-1] == (f"5. filter by agent:fake ✓ (edited) → "
                                                  f"{short(edited.outputs[0])} (lincoln_filter)")
    failing = session.run_tool("cutout", {"image": work.id, "box": [0, 0, 1, 1], "no_ai": True}, "user")
    assert session.take_changes() == [
        f'the user ran step 6: cutout {{"image": "{short(work.id)}", "box": [0, 0, 1, 1], "no_ai": true}}, '
        f"which failed: {failing.error.message}"]
    assert session.last_output() == edited.outputs[0]


def test_the_agent_hears_about_pictures_the_user_adds(tmp_path):
    """Spec 5.3: a picture the user adds without attaching it to a message still reaches the agent's next
    system note. A picture a step brings in is that step's news: its tool result, or the user's run note."""
    red = png(Image.new("RGB", (1500, 1200), "red"))
    src = {"kind": "url", "url": "http://127.0.0.1:8000/red.png", "page": None, "title": None,
           "license": None, "creator": None}
    fetched = ToolOutcome(True, [OutputRecord("1", red, "fetch/red_1.png")], [], {"sources": [src]})
    seen = []
    s = Session.new(output_dir=tmp_path, executor=ScriptedExecutor(fetched, fetched),
                    on_change=lambda: seen.append(list(s.changes)))
    work = s.import_image(LINCOLN, "lincoln")
    assert seen == [[f"the user added image {short(work.id)} (lincoln_work)"]]  # noted before the autosave
    trump = s.import_image(TRUMP, "trump.png")
    s.import_image(LINCOLN, "lincoln_again.png")  # the same picture before the agent heard: still one line
    assert s.take_changes() == [f"the user added image {short(work.id)} (lincoln_work)",
                                f"the user added image {short(trump.id)} (trump_work)"]
    s.import_image(LINCOLN, "lincoln")  # once the agent has heard, adding it again is news again
    assert s.take_changes() == [f"the user added image {short(work.id)} (lincoln_work)"]
    agents = s.run_tool("fetch", {"query": "red"}, "agent:fake")
    assert agents.status == "done" and s.take_changes() == []  # its pictures are in the agent's tool result
    users = s.run_tool("fetch", {"query": "red"}, "user")
    assert users.status == "done" and users.outputs == agents.outputs
    assert [c.split(":")[0] for c in s.take_changes()] == ["the user ran step 2"]  # the run note, no "added"


def test_messages(session):
    work = session.import_image(LINCOLN, "lincoln")
    m1 = session.add_message("user", [Part(type="text", text="make it bad"),
                                      Part(type="image", artifact_id=work.id[:7])])
    assert m1.id == "m1" and m1.content[1].artifact_id == work.id and session.data.messages == [m1]
    with pytest.raises(EngineError, match="no such artifact: deadbeef00"):
        session.add_message("user", [Part(type="image", artifact_id="deadbeef00")])
    with pytest.raises(EngineError, match="needs an artifact id"):
        session.add_message("user", [Part(type="image")])
    with pytest.raises(EngineError, match="no such step: s4"):
        session.add_message("assistant", [Part(type="text", text="done")], step_ids=["s4"])
    assert session.add_message("system_note", [Part(type="text", text="x")]).id == "m2"


def test_ids_are_never_reused(tmp_path):
    # a reopened project whose last step (s4) was deleted while a message still names it
    data = SessionData(id="x", name="old", created_at=0.0,
                       messages=[Message(id="m2", role="assistant", content=[], step_ids=["s4"])])
    s = Session(data, ArtifactStore(), output_dir=tmp_path)
    work = s.import_image(LINCOLN, "lincoln")
    step = s.propose("prep", {"image": work.id}, "user")
    assert (step.id, step.index) == ("s5", 1)
    assert s.add_message("user", [Part(type="text", text="hi")]).id == "m3"


def test_on_change_after_every_settled_change(tmp_path):
    seen = []
    s = Session.new(output_dir=tmp_path, on_change=lambda: seen.append([st.status for st in s.data.steps]))
    work = s.import_image(LINCOLN, "lincoln")
    s.run_tool("filter", {"image": work.id, "names": ["invert"]}, "user")
    s.reject(s.propose("filter", {"image": work.id, "names": ["sepia"]}, "user").id)
    s.add_message("user", [Part(type="text", text="hi")])
    assert seen == [[], ["proposed"], ["done"], ["done", "proposed"], ["done", "rejected"],
                    ["done", "rejected"]]  # an autosave never catches a step mid-run


def test_result_text_without_an_outcome(session):
    work = session.import_image(LINCOLN, "lincoln")
    step = session.run_tool("prep", {"image": work.id}, "user")
    w, g = (session.artifacts.meta[i] for i in step.outputs)
    assert result_text(step, session.artifacts) == f"1: {describe(w)}\n2: {describe(g)}"
