import asyncio
import json
import threading
import time

import pytest

from badshop.agent.approval import ApprovalGate, Decision, needs_approval
from badshop.agent.context import SYSTEM_PROMPT, build_messages, image_placeholder, tool_definitions
from badshop.agent.fake import END_OF_SCRIPT, ScriptedProvider
from badshop.agent.loop import TurnConfig, run_turn
from badshop.agent.provider import ProviderError, Reply, ToolCallRequest
from badshop.engine.errors import EngineError
from badshop.session import execution
from badshop.session.execution import InProcessExecutor, ToolOutcome
from badshop.session.models import Step
from badshop.session.session import Session
from badshop.tools import REGISTRY
from badshop.tools.registry import get, llm_schema
from conftest import FIXTURES

LINCOLN = (FIXTURES / "lincoln.png").read_bytes()
TRUMP = (FIXTURES / "trump.png").read_bytes()
LIMIT = 10  # seconds: every wait in this file has one, so a lost decision or a missing event fails, not hangs


class Events:
    """An Emit that records (name, payload) pairs (a plain object: an empty list would be falsy)."""

    def __init__(self):
        self.log: list[tuple[str, dict]] = []

    def __call__(self, name: str, payload: dict) -> None:
        self.log.append((name, payload))

    def names(self) -> list[str]:
        out: list[str] = []
        for name, _ in self.log:
            if not (out and name == out[-1] == "message.delta"):  # a stream counts once
                out.append(name)
        return out[out.index("turn.started"):] if "turn.started" in out else out  # the turn's own events

    def of(self, name: str) -> list[dict]:
        return [p for n, p in self.log if n == name]


def new_session(tmp_path, executor=None):
    ev = Events()
    session = Session.new(emit=ev, output_dir=tmp_path, executor=executor)
    img = session.import_image(LINCOLN, "lincoln")
    session.take_changes()  # the import's change note: the tests of that note import their own pictures
    return session, img, ev


def call(id: str, name: str, arguments: dict | str | None = None) -> ToolCallRequest:
    return ToolCallRequest(id=id, name=name, arguments={} if arguments is None else arguments)


def turn(session, provider, ev, mode="auto", text="go", attachments=(), decide=None, cfg=None, **kw):
    """Run one turn; `decide(gate, step_dict)` answers each approval on the loop's next iteration."""
    cfg = cfg or TurnConfig(approval_mode=mode, **kw)

    async def main():
        loop = asyncio.get_running_loop()

        def emit(name, payload):
            ev(name, payload)
            if name == "approval.needed" and decide:
                loop.call_soon(decide, gate, payload["step"])

        gate = ApprovalGate(emit)
        reason = await asyncio.wait_for(run_turn(session, provider, gate, text, list(attachments), cfg, emit),
                                        LIMIT)
        return reason, gate

    return asyncio.run(main())


async def until_approval(session, provider, ev, mode="ask_all"):
    """Start a turn as a task (inside a running loop) and return it and its gate once a step waits."""
    needed = asyncio.Event()

    def emit(name, payload):
        ev(name, payload)
        if name == "approval.needed":
            needed.set()

    gate = ApprovalGate(emit)
    cfg = TurnConfig(approval_mode=mode)
    task = asyncio.create_task(run_turn(session, provider, gate, "go", [], cfg, emit))
    await asyncio.wait_for(needed.wait(), LIMIT)
    return task, gate


def tool_entries(session) -> dict[str, str]:
    return {e["tool_call_id"]: e["content"] for e in session.data.transcript if e["role"] == "tool"}


def every_call_answered(transcript: list[dict]) -> bool:
    calls = [c["id"] for e in transcript if e["role"] == "assistant" for c in e.get("tool_calls") or []]
    answers = [e["tool_call_id"] for e in transcript if e["role"] == "tool"]
    return sorted(calls) == sorted(answers)


def test_needs_approval_modes():
    find, cutout, export = get("find"), get("cutout"), get("export")
    assert [needs_approval(s, "auto") for s in (find, cutout, export)] == [False, False, False]
    assert [needs_approval(s, "ask_changes") for s in (find, cutout, export)] == [False, True, True]
    assert [needs_approval(s, "ask_all") for s in (find, cutout, export)] == [True, True, True]
    with pytest.raises(EngineError, match="unknown approval mode"):
        needs_approval(find, "yolo")


def test_scripted_provider_streams_records_and_ends():
    provider = ScriptedProvider([Reply(text="Putting the head on Lincoln now.",
                                       tool_calls=[call("c1", "info", {"image": "abcdef"})])])
    messages = [{"role": "user", "content": "hi"}]
    chunks: list[str] = []
    reply = asyncio.run(provider.complete(messages, [], chunks.append))
    assert "".join(chunks) == "Putting the head on Lincoln now." and len(chunks) > 1
    assert reply.tool_calls == [call("c1", "info", {"image": "abcdef"})]
    messages[0]["content"] = "changed later"
    assert provider.received == [[{"role": "user", "content": "hi"}]]  # a copy of what was sent
    end = asyncio.run(provider.complete([], [], chunks.append))
    assert end == Reply(text=END_OF_SCRIPT) and len(provider.received) == 2


def test_scripted_provider_from_file(tmp_path):
    script = tmp_path / "script.json"
    script.write_text(json.dumps([
        {"text": "one", "tool_calls": [{"name": "info", "arguments": {"image": "abcdef"}},
                                       {"name": "view", "arguments": "{broken"}]},
        {"error": "rate limited (429)"},
        {"tool_calls": [{"name": "find"}]},
    ]), encoding="utf-8")
    provider = ScriptedProvider.from_file(script)

    async def play():
        first = await provider.complete([], [], lambda chunk: None)
        with pytest.raises(ProviderError, match="rate limited"):
            await provider.complete([], [], lambda chunk: None)
        return first, await provider.complete([], [], lambda chunk: None)

    first, third = asyncio.run(play())
    assert first.text == "one"
    assert first.tool_calls == [call("call_1", "info", {"image": "abcdef"}),
                                call("call_2", "view", "{broken")]
    assert third == Reply(tool_calls=[call("call_3", "find", {})])  # ids run on across the script
    with pytest.raises(EngineError, match="can't read the fake provider script"):
        ScriptedProvider.from_file(tmp_path / "missing.json")


@pytest.mark.parametrize("content", ["not json", '{"text": "a dict, not a list"}',
                                     '[{"text": "x", "tool_calls": [{"arguments": {}}]}]'])
def test_scripted_provider_bad_file(tmp_path, content):
    script = tmp_path / "script.json"
    script.write_text(content, encoding="utf-8")
    with pytest.raises(EngineError, match="fake provider script") as e:
        ScriptedProvider.from_file(script)
    assert e.value.hint


def test_tool_definitions_are_the_model_schemas():
    defs = {d["function"]["name"]: d for d in tool_definitions()}
    assert set(defs) == set(REGISTRY)
    for name, d in defs.items():
        assert d["type"] == "function"
        assert d["function"]["description"] == REGISTRY[name].description
        assert d["function"]["parameters"] == llm_schema(REGISTRY[name])
    assert "clipboard" not in defs["fetch"]["function"]["parameters"]["properties"]  # user-only
    json.dumps(defs)


def test_system_prompt_placeholder_and_step_summary(tmp_path):
    session, img, _ = new_session(tmp_path)
    assert "artifact id" in SYSTEM_PROMPT and "nearest-neighbor" in SYSTEM_PROMPT
    assert image_placeholder(img) == f"[image {img.id[:8]}: lincoln_work, {img.width}x{img.height}]"
    assert build_messages(session) == [{"role": "system", "content": SYSTEM_PROMPT + "\n\nNo steps yet."}]
    session.run_tool("info", {"image": img.id}, "user")
    session.data.transcript.append({"role": "user", "content": "hello"})
    system, user = build_messages(session)
    assert system["content"] == f"{SYSTEM_PROMPT}\n\nSteps so far:\n{session.summary()}"
    assert user == {"role": "user", "content": "hello"}


def test_build_messages_answers_dangling_calls(tmp_path):
    session, _, _ = new_session(tmp_path)

    def asking(*ids):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "info", "arguments": "{}"}} for i in ids]}

    session.data.transcript = [{"role": "user", "content": "go"}, asking("a", "b"),
                               {"role": "tool", "tool_call_id": "a", "content": "ok"},
                               {"role": "user", "content": "again"}, asking("c")]
    messages = build_messages(session)[1:]
    assert [(m["role"], m.get("tool_call_id")) for m in messages] == [
        ("user", None), ("assistant", None), ("tool", "a"), ("tool", "b"), ("user", None),
        ("assistant", None), ("tool", "c")]
    assert messages[3]["content"].startswith("not run") and every_call_answered(messages)
    assert len(session.data.transcript) == 5  # the stored transcript is left alone


def test_turn_runs_tools_and_reports_back(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([
        Reply(text="Circling his face.",
              tool_calls=[call("c1", "draw", {"image": img.id[:8], "circle": [[200, 150, 60]]})]),
        Reply(text="Done: a red circle."),
    ])
    reason, _ = turn(session, provider, ev, mode="auto", text="circle the face")
    assert reason == "done"
    assert ev.names() == ["turn.started", "message.done", "message.delta", "message.done", "step.proposed",
                          "message.done", "step.started", "step.finished", "message.delta", "message.done",
                          "turn.finished"]
    assert "".join(p["text"] for p in ev.of("message.delta")) == "Circling his face.Done: a red circle."
    assert ev.of("turn.finished") == [{"reason": "done"}]
    step = session.data.steps[0]
    assert (step.tool, step.actor, step.status) == ("draw", "agent:fake", "done")
    assert step.reason == "Circling his face." and step.params["image"] == img.id  # the short ref resolved
    assert [m.role for m in session.data.messages] == ["user", "assistant", "assistant"]
    assert session.data.messages[1].step_ids == [step.id]
    # The reply is sent again once its call is a step, so a client that only follows events links them.
    done = [p["message"] for p in ev.of("message.done")]
    assert [m["id"] for m in done] == ["m1", "m2", "m2", "m3"]
    assert done[1]["step_ids"] == [] and done[2] == session.data.messages[1].model_dump(mode="json")
    user, asked, answer, final = session.data.transcript
    assert user == {"role": "user", "content": "circle the face"}
    assert asked["role"] == "assistant" and asked["content"] == "Circling his face."
    assert asked["tool_calls"][0]["id"] == "c1"
    assert json.loads(asked["tool_calls"][0]["function"]["arguments"]) == {"image": img.id[:8],
                                                                           "circle": [[200, 150, 60]]}
    assert answer == {"role": "tool", "tool_call_id": "c1", "content": step.result_text}
    assert step.outputs[0][:8] in answer["content"] and "drew 1 shape" in answer["content"]  # + tool lines
    assert final == {"role": "assistant", "content": "Done: a red circle."}
    second = provider.received[1]
    assert session.summary() in second[0]["content"] and second[-1] == answer


def test_attachments_are_resolved_and_shown_as_placeholders(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([Reply(text="Nice picture.")])
    turn(session, provider, ev, text="look", attachments=[img.id[:6].upper()])
    user = session.data.messages[0]
    assert [(p.type, p.text, p.artifact_id) for p in user.content] == [("text", "look", None),
                                                                     ("image", None, img.id)]
    assert provider.received[0][-1] == {"role": "user", "content": f"look\n{image_placeholder(img)}"}
    before, quiet = list(session.data.messages), Events()
    with pytest.raises(EngineError, match="no such artifact"):
        turn(session, provider, quiet, attachments=["/etc/passwd"])
    assert session.data.messages == before and quiet.log == []  # nothing recorded, nothing emitted


def test_user_changes_open_the_turn_as_a_system_note(tmp_path):
    session, img, ev = new_session(tmp_path)
    session.run_tool("filter", {"image": img.id, "names": ["invert"]}, "user")
    changes = list(session.changes)
    assert changes  # a user-run step is news to the agent
    provider = ScriptedProvider([Reply(text="ok")])
    turn(session, provider, ev, text="now what")
    note = session.data.messages[0]
    assert note.role == "system_note" and all(c in note.content[0].text for c in changes)
    assert session.data.transcript[0] == {"role": "system", "content": note.content[0].text}
    assert session.data.transcript[1] == {"role": "user", "content": "now what"}
    assert provider.received[0][1] == session.data.transcript[0]
    assert session.changes == []
    turn(session, ScriptedProvider([Reply(text="ok")]), ev, text="again")
    assert [m.role for m in session.data.messages].count("system_note") == 1  # heard once


def test_an_image_the_user_adds_is_news_to_the_agent(tmp_path):
    # Spec §5.3 (ruling R5): a picture the user drops in without attaching it to a message still reaches
    # the model, as a line of the next turn's system note (Session.import_image writes the change note).
    ev = Events()
    session = Session.new(emit=ev, output_dir=tmp_path)
    lincoln = session.import_image(LINCOLN, "lincoln")
    provider = ScriptedProvider([Reply(text="I see Lincoln."), Reply(text="And now Trump.")])
    assert turn(session, provider, ev, text="what have we got?")[0] == "done"
    note = session.data.messages[0]
    assert note.role == "system_note"
    assert ev.of("message.done")[0] == {"message": note.model_dump(mode="json")}  # the chat shows it too
    [added] = [line for line in note.content[0].text.splitlines() if lincoln.id[:8] in line]
    assert f"{lincoln.id[:8]} (lincoln_work)" in added  # the id the model can call tools with, and its label
    sent = provider.received[0]
    assert sent[1] == session.data.transcript[0] == {"role": "system", "content": note.content[0].text}
    assert sent[2] == {"role": "user", "content": "what have we got?"}  # not attached: no placeholder
    # Heard once: the next turn's note carries only what the user added since.
    trump = session.import_image(TRUMP, "trump")
    assert turn(session, provider, ev, text="and now?")[0] == "done"
    notes = [m.content[0].text for m in session.data.messages if m.role == "system_note"]
    assert len(notes) == 2 and f"{trump.id[:8]} (trump_work)" in notes[1]
    assert lincoln.id[:8] not in notes[1]
    assert provider.received[1][-2:] == [{"role": "system", "content": notes[1]},
                                         {"role": "user", "content": "and now?"}]
    assert session.changes == []


def test_ask_changes_runs_read_only_tools_and_waits_for_the_rest(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([
        Reply(text="Measuring, then inverting.",
              tool_calls=[call("c1", "info", {"image": img.id}),
                          call("c2", "filter", {"image": img.id, "names": ["invert"]})]),
        Reply(text="Inverted."),
    ])
    reason, gate = turn(session, provider, ev, mode="ask_changes",
                        decide=lambda gate, step: gate.respond(step["id"], "approve"))
    assert reason == "done" and gate.pending() == []
    needed = ev.of("approval.needed")
    assert [p["step"]["tool"] for p in needed] == ["filter"]
    assert needed[0]["step"]["reason"] == "Measuring, then inverting."
    assert ev.of("approval.resolved") == [{"step_id": "s2", "decision": "approve", "note": None}]
    assert [s.status for s in session.data.steps] == ["done", "done"]


def test_reject_tells_the_model_why(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([
        Reply(tool_calls=[call("c1", "filter", {"image": img.id, "names": ["emboss"]})]),
        Reply(text="Fine, no emboss."),
    ])
    reason, _ = turn(session, provider, ev, mode="ask_all",
                     decide=lambda gate, step: gate.respond(step["id"], "reject", note="too subtle"))
    assert reason == "done"
    step = session.data.steps[0]
    assert step.status == "rejected" and step.outputs == []
    assert tool_entries(session) == {"c1": "rejected by user: too subtle"}
    assert "step.started" not in ev.names()


def test_edit_runs_with_the_users_parameters(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([
        Reply(tool_calls=[call("c1", "draw", {"image": img.id, "circle": [[10, 10, 5]]})]),
        Reply(text="ok"),
    ])
    edited = {"image": img.id, "circle": [[200, 150, 60]], "color": "blue"}
    reason, _ = turn(session, provider, ev, mode="ask_all",
                     decide=lambda gate, step: gate.respond(step["id"], "edit", params=edited))
    step = session.data.steps[0]
    assert reason == "done" and step.status == "done"
    assert step.params["circle"] == [[200, 150, 60]] and step.params["color"] == "blue"
    assert ev.of("approval.resolved")[0]["decision"] == "edit"
    content = tool_entries(session)["c1"]
    assert content.startswith("the user edited the parameters before it ran:") and '"blue"' in content
    assert content.endswith(step.result_text)


def test_an_edit_the_session_refuses_is_a_rejection(tmp_path):
    # The fallback for a gate without `resolve` (the server's gate refuses this edit at respond(), below).
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([
        Reply(tool_calls=[call("c1", "draw", {"image": img.id, "circle": [[9, 9, 5]]})]),
        Reply(text="ok"),
    ])
    unknown = {"image": "ffffff", "circle": [[9, 9, 5]]}  # valid parameters, but no such artifact
    reason, _ = turn(session, provider, ev, mode="ask_all",
                     decide=lambda gate, step: gate.respond(step["id"], "edit", params=unknown))
    assert reason == "done" and session.data.steps[0].status == "rejected"
    assert tool_entries(session)["c1"].startswith("rejected by user: their edited parameters were refused")


def test_mode_switched_mid_turn_applies_to_the_next_call(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([Reply(tool_calls=[
        call("c1", "filter", {"image": img.id, "names": ["invert"]}),
        call("c2", "filter", {"image": img.id, "names": ["grayscale"]})])])
    cfg = TurnConfig(approval_mode="ask_all")

    def approve_and_trust(gate, step):
        cfg.approval_mode = "auto"  # what the server does on session.set_approval_mode
        gate.respond(step["id"], "approve")

    turn(session, provider, ev, cfg=cfg, decide=approve_and_trust)
    assert [p["step"]["id"] for p in ev.of("approval.needed")] == ["s1"]
    assert [s.status for s in session.data.steps] == ["done", "done"]


def test_invalid_calls_come_back_as_errors_and_end_the_turn(tmp_path):
    session, img, ev = new_session(tmp_path)
    provider = ScriptedProvider([
        Reply(tool_calls=[call("c1", "draw", "{not json"), call("c2", "sharpen_everything", {})]),
        Reply(tool_calls=[call("c3", "info", {"image": img.id})]),  # valid: the count starts over
        Reply(tool_calls=[call("c4", "draw", {"image": img.id, "width": 0}),
                          call("c5", "fetch", {"query": "cat", "clipboard": True}),
                          call("c6", "info", {"image": "/etc/passwd"}),
                          call("c7", "info", {"image": img.id})]),
    ])
    reason, _ = turn(session, provider, ev, mode="auto")
    assert reason == "invalid_calls" and len(provider.received) == 3
    assert [s.tool for s in session.data.steps] == ["info"]  # invalid calls never become steps
    got = tool_entries(session)
    assert got["c1"].startswith("error: the arguments for draw are not valid JSON")
    assert got["c2"].startswith("error: unknown tool 'sharpen_everything'")
    assert got["c3"] == session.data.steps[0].result_text
    assert got["c4"].startswith("error: bad parameters for draw\nhint: ") and "width" in got["c4"]
    assert got["c5"].startswith("error: fetch: clipboard can only be set by the user")
    assert got["c6"].startswith("error: no such artifact: /etc/passwd")
    assert got["c7"].startswith("not run: 3 invalid calls in a row")
    assert every_call_answered(session.data.transcript)
    assert ev.of("turn.finished") == [{"reason": "invalid_calls"}]


def test_failed_steps_are_results_not_invalid_calls(tmp_path):
    session, img, ev = new_session(tmp_path)
    nothing = {"image": img.id}  # valid parameters, but nothing to draw
    provider = ScriptedProvider([Reply(tool_calls=[call(f"x{i}", "draw", nothing)]) for i in range(3)]
                                + [Reply(text="I give up.")])
    reason, _ = turn(session, provider, ev, mode="auto")
    assert reason == "done"
    assert [s.status for s in session.data.steps] == ["error"] * 3
    content = tool_entries(session)["x0"]
    assert content == session.data.steps[0].result_text
    assert content.startswith("error: nothing to draw") and "give circle, arrow, line or rect" in content


def test_step_budget(tmp_path):
    session, img, ev = new_session(tmp_path)
    info = {"image": img.id}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "info", info), call("c2", "info", info),
                                                   call("c3", "info", info)])])
    reason, _ = turn(session, provider, ev, mode="auto", step_budget=2)
    assert reason == "budget" and len(session.data.steps) == 2 and len(provider.received) == 1
    assert tool_entries(session)["c3"].startswith("not run: this turn's budget of 2 steps is used up")
    assert ev.of("turn.finished")[-1] == {"reason": "budget"}
    # A model that answers after spending exactly the budget still finishes normally.
    provider = ScriptedProvider([Reply(tool_calls=[call("c4", "info", info)]), Reply(text="done")])
    assert turn(session, provider, ev, mode="auto", step_budget=1)[0] == "done"
    # Only steps this turn ran use the budget: an invalid call, a rejected step and a step something else
    # ran while it waited (see settle() below) don't.
    provider = ScriptedProvider([Reply(tool_calls=[call("c5", "info", "{bad"), call("c6", "info", info),
                                                   call("c7", "info", info), call("c8", "info", info)]),
                                 Reply(text="done")])
    plan = iter(["reject", "settled", "approve"])

    def decide(gate, step):
        how = next(plan)
        if how == "settled":
            session.run(step["id"])
        gate.respond(step["id"], "reject" if how == "reject" else "approve")

    reason, _ = turn(session, provider, ev, mode="ask_all", step_budget=1, decide=decide)
    assert reason == "done" and [s.status for s in session.data.steps[-3:]] == ["rejected", "done", "done"]
    assert tool_entries(session)["c7"] == session.data.steps[-2].result_text


def test_provider_error_ends_the_turn(tmp_path):
    session, _, ev = new_session(tmp_path)
    reason, _ = turn(session, ScriptedProvider([ProviderError("rate limited (429)")]), ev, text="hi")
    assert reason == "provider_error"
    assert ev.of("turn.finished") == [{"reason": "provider_error", "error": "rate limited (429)"}]
    assert session.data.transcript == [{"role": "user", "content": "hi"}]  # retry-able as it stands


def test_unexpected_failure_still_finishes_the_turn(tmp_path):
    class Broken:
        actor = "agent:test"

        async def complete(self, messages, tools, on_delta):
            raise RuntimeError("boom")

    session, _, ev = new_session(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        turn(session, Broken(), ev)
    assert ev.of("turn.finished") == [{"reason": "error", "error": "RuntimeError: boom"}]


def test_gate_respond_checks_its_input(tmp_path):
    session, img, _ = new_session(tmp_path)
    step = Step(id="s1", index=1, tool="draw", params={"image": img.id, "circle": [[5, 5, 3]]},
                actor="agent:fake", status="proposed")
    ev = Events()

    async def main():
        gate = ApprovalGate(ev, resolve=session.artifacts.resolve)  # as the server builds it
        waiting = asyncio.create_task(gate.request(step))
        await asyncio.sleep(0)
        assert gate.pending() == ["s1"]
        with pytest.raises(EngineError, match="not waiting"):
            gate.respond("s9", "approve")
        with pytest.raises(EngineError, match="unknown decision"):
            gate.respond("s1", "maybe")
        with pytest.raises(EngineError, match="needs the new parameters"):
            gate.respond("s1", "edit")
        with pytest.raises(EngineError, match="bad parameters for draw"):
            gate.respond("s1", "edit", params={"image": img.id, "width": 0})
        with pytest.raises(EngineError, match="no such artifact: ffffff"):  # a mistyped id in the edit form
            gate.respond("s1", "edit", params={"image": "ffffff", "rect": [[1, 1, 9, 9]]})
        with pytest.raises(EngineError, match="parameters go with decision 'edit'"):
            gate.respond("s1", "approve", params={"image": img.id})
        assert gate.pending() == ["s1"] and not waiting.done()  # every refusal kept it waiting
        gate.respond("s1", "edit", params={"image": img.id[:8], "rect": [[1, 1, 9, 9]]})
        decision = await asyncio.wait_for(waiting, LIMIT)
        with pytest.raises(EngineError, match="not waiting"):
            gate.respond("s1", "approve")
        return decision

    # The decision carries the user's params as sent: the session resolves them when the step runs.
    assert asyncio.run(main()) == Decision("edit", {"image": img.id[:8], "rect": [[1, 1, 9, 9]]}, None)
    assert ev.names() == ["approval.needed", "approval.resolved"]


def test_gate_cancel_all_rejects_everything_waiting():
    steps = [Step(id=f"s{i}", index=i, tool="info", params={}, actor="agent:fake", status="proposed")
             for i in (1, 2)]
    ev = Events()

    async def main():
        gate = ApprovalGate(ev)
        waiting = [asyncio.create_task(gate.request(s)) for s in steps]
        await asyncio.sleep(0)
        gate.cancel_all()
        assert gate.pending() == []
        return await asyncio.wait_for(asyncio.gather(*waiting), LIMIT)

    assert asyncio.run(main()) == [Decision("reject", note="the user closed the app")] * 2
    closed = "the user closed the app"
    assert ev.of("approval.resolved") == [{"step_id": s, "decision": "reject", "note": closed}
                                          for s in ("s1", "s2")]


class Counting(InProcessExecutor):
    """Runs tools here, and counts the cancel() calls a real worker would act on."""

    def __init__(self):
        self.cancels = 0

    def cancel(self):
        self.cancels += 1


@pytest.mark.parametrize("how, note", [("stop", "stopped by the user"),  # chat.stop cancels the turn
                                       ("client_gone", "the user closed the app")])  # the server's order
def test_stop_while_waiting_for_approval(tmp_path, how, note):
    executor = Counting()
    session, img, ev = new_session(tmp_path, executor=executor)
    provider = ScriptedProvider([Reply(text="Three things.", tool_calls=[
        call("c1", "info", {"image": img.id}),
        call("c2", "filter", {"image": img.id, "names": ["invert"]}),
        call("c3", "filter", {"image": img.id, "names": ["sepia"]})])])

    async def main():
        needed = asyncio.Event()

        def emit(name, payload):
            ev(name, payload)
            if name == "approval.needed":
                needed.set()

        gate = ApprovalGate(emit)
        task = asyncio.create_task(run_turn(session, provider, gate, "go", [], TurnConfig(), emit))
        await asyncio.wait_for(needed.wait(), LIMIT)
        assert gate.pending() == ["s2"]
        if how == "client_gone":
            gate.cancel_all()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, LIMIT)
        return gate

    gate = asyncio.run(main())
    assert executor.cancels == 0  # no tool was running: a worker must not carry a cancel into the next call
    assert gate.pending() == []
    assert [(s.id, s.status) for s in session.data.steps] == [("s1", "done"), ("s2", "rejected")]
    assert ev.of("approval.resolved") == [{"step_id": "s2", "decision": "reject", "note": note}]
    assert ev.names()[-1] == "turn.finished" and ev.of("turn.finished") == [{"reason": "stopped"}]
    assert tool_entries(session) == {"c1": session.data.steps[0].result_text,
                                     "c2": "not run: stopped by the user",
                                     "c3": "not run: stopped by the user"}
    # The session is whole: the next turn sends a transcript every provider accepts.
    nxt = ScriptedProvider([Reply(text="ok")])
    assert turn(session, nxt, ev, text="carry on")[0] == "done"
    assert every_call_answered(nxt.received[0])


def test_approvals_wait_outside_the_servers_lock(tmp_path):
    session, img, ev = new_session(tmp_path)
    invert = {"image": img.id, "names": ["invert"]}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "filter", invert)]), Reply(text="ok")])

    async def main():
        lock = asyncio.Lock()

        async def locked(fn, *args):  # the server's `blocking`: one session call at a time
            async with lock:
                return await asyncio.to_thread(fn, *args)

        needed = asyncio.Event()

        def emit(name, payload):
            ev(name, payload)
            if name == "approval.needed":
                needed.set()

        gate = ApprovalGate(emit)
        task = asyncio.create_task(run_turn(session, provider, gate, "go", [], TurnConfig(), emit, locked))
        await asyncio.wait_for(needed.wait(), LIMIT)
        # While a step waits for approval the lock is free, so the user can still run tools.
        mine = await asyncio.wait_for(locked(session.run_tool, "info", {"image": img.id}, "user"), 10)
        gate.respond("s1", "approve")
        return mine, await asyncio.wait_for(task, 10)

    mine, reason = asyncio.run(main())
    assert reason == "done" and mine.status == "done"
    assert [(s.tool, s.status) for s in session.data.steps] == [("filter", "done"), ("info", "done")]


def test_a_waiting_step_is_out_of_the_users_reach(tmp_path):
    # Approvals wait outside the server's lock, so the user can act while a step waits. Task 8 refuses to
    # edit, replay or delete a proposed step: the approval card is the only way to change it.
    session, img, ev = new_session(tmp_path)
    invert = {"image": img.id, "names": ["invert"]}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "filter", invert)]), Reply(text="ok")])

    async def main():
        task, gate = await until_approval(session, provider, ev)
        for attempt in (lambda: session.edit("s1", {"image": img.id, "names": ["sepia"]}),
                        lambda: session.replay_from("s1"),
                        lambda: session.delete_last("s1")):
            with pytest.raises(EngineError, match="is waiting for approval"):
                await asyncio.to_thread(attempt)
        assert gate.pending() == ["s1"] and session.step("s1").status == "proposed"
        gate.respond("s1", "approve")
        return await asyncio.wait_for(task, LIMIT)

    assert asyncio.run(main()) == "done"
    step = session.step("s1")
    assert step.status == "done" and step.params["names"] == ["invert"] and not step.edited
    assert tool_entries(session) == {"c1": step.result_text}


def settle(session, step, how):
    """Settle a waiting step behind the gate's back. Nothing in Plan 2 does this but Session.run (it takes
    any proposed step); the loop must answer the call all the same, never raise over it."""
    if how == "ran":
        session.run(step.id)
    elif how == "rejected":
        session.reject(step.id, "not now")
    elif how == "stale":
        step.status = "stale"
    else:  # "deleted", the way delete_last would
        session.data.steps.remove(step)
        for m in session.data.messages:
            m.step_ids = [i for i in m.step_ids if i != step.id]


@pytest.mark.parametrize("ending", ["approve", "reject", "stop"])
@pytest.mark.parametrize("how", ["ran", "rejected", "stale", "deleted"])
def test_a_step_settled_elsewhere_while_it_waited(tmp_path, how, ending):
    session, img, ev = new_session(tmp_path)
    invert = {"image": img.id, "names": ["invert"]}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "filter", invert)]), Reply(text="ok")])

    async def main():
        task, gate = await until_approval(session, provider, ev)
        await asyncio.to_thread(settle, session, session.step("s1"), how)
        if ending == "stop":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, LIMIT)
            return "stopped"
        gate.respond("s1", ending)
        return await asyncio.wait_for(task, LIMIT)

    reason = asyncio.run(main())
    assert reason == ("stopped" if ending == "stop" else "done")
    assert ev.of("turn.finished") == [{"reason": reason}]
    left = next((s for s in session.data.steps if s.id == "s1"), None)
    if how == "deleted":
        assert left is None
        answer = "the user deleted this step" if ending == "stop" else "not run: the user deleted this step"
    else:
        assert left.status == {"ran": "done", "rejected": "rejected", "stale": "stale"}[how]
        answer = {"ran": left.result_text, "rejected": "rejected by user: not now",
                  "stale": "not run: the user changed this step (it is stale now)"}[how]
    assert tool_entries(session) == {"c1": answer} and every_call_answered(session.data.transcript)
    assert ev.names().count("step.started") == (1 if how == "ran" else 0)  # the loop itself ran nothing


def test_every_tool_result_reaches_the_autosave_hook(tmp_path):
    saved: list[dict] = []  # the session as each on_change saw it
    session = Session.new(output_dir=tmp_path,
                          on_change=lambda: saved.append(session.data.model_dump(mode="json", by_alias=True)))
    img = session.import_image(LINCOLN, "lincoln")
    info = {"image": img.id}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "info", info), call("c2", "info", info),
                                                   call("c3", "info", info)])])
    assert turn(session, provider, Events(), step_budget=2)[0] == "budget"
    # The last save holds every answer (c3's "not run" included) and the reply's link to its steps. The
    # import's change note opens the turn, so the reply is the third message.
    assert saved[-1] == session.data.model_dump(mode="json", by_alias=True)
    assert every_call_answered(saved[-1]["transcript"])
    assert [(m["role"], m["step_ids"]) for m in saved[-1]["messages"]] == [
        ("system_note", []), ("user", []), ("assistant", ["s1", "s2"])]


class HeldExecutor:
    """Holds every tool call until the call's own cancel event is set: a slow tool in the worker process, as
    the loop sees it. A killed worker takes a moment to report back, so a Stop that doesn't wait for the call
    answers early."""

    def __init__(self):
        self.started = threading.Event()
        self.cancels = 0

    def run(self, call, cancel=None):
        self.started.set()
        stopped = cancel is not None and cancel.wait(LIMIT)
        time.sleep(0.2)  # the kill and the report
        return ToolOutcome(ok=False, error_message="stopped by the user" if stopped else "never stopped")

    def cancel(self):
        self.cancels += 1

    def close(self):
        pass


def test_stop_while_a_tool_runs(tmp_path):
    executor = HeldExecutor()
    session, img, ev = new_session(tmp_path, executor=executor)
    invert = {"image": img.id, "names": ["invert"]}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "filter", invert)])])

    async def main():
        cfg = TurnConfig(approval_mode="auto")
        task = asyncio.create_task(run_turn(session, provider, ApprovalGate(ev), "go", [], cfg, ev))
        assert await asyncio.to_thread(executor.started.wait, LIMIT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, LIMIT)

    asyncio.run(main())
    step = session.data.steps[0]
    assert executor.cancels == 0  # the step's own event stopped it: the loop never calls cancel()
    assert step.status == "error" and step.error.message == "stopped by the user"
    names = ev.names()
    assert names.index("step.failed") < names.index("turn.finished") == len(names) - 1  # waited for the tool
    assert tool_entries(session) == {"c1": step.result_text}
    assert tool_entries(session)["c1"].startswith("error: stopped by the user")


def test_a_stop_before_the_executor_begins_still_stops_the_step(tmp_path, monkeypatch):
    """Stop lands after the step's thread is dispatched but before the executor's run() begins: Session.run
    is still validating, naming the outputs, announcing step.started, or waiting for the server's lock. The
    executor-wide cancel() can't reach a call that hasn't begun (WorkerExecutor.run starts each call afresh);
    the step's own cancel event can, so the tool never runs and the step ends stopped at once."""
    executor = Counting()
    session, img, ev = new_session(tmp_path, executor=executor)
    invert = {"image": img.id, "names": ["invert"]}
    provider = ScriptedProvider([Reply(tool_calls=[call("c1", "filter", invert)])])
    ran: list[str] = []
    real_execute_call, real_run = execution.execute_call, Session.run
    monkeypatch.setattr(execution, "execute_call", lambda c: ran.append(c.tool) or real_execute_call(c))
    dispatched = threading.Event()

    def held_run(self, step_id, raw=None, **kw):  # the step's thread, held before it reaches the executor
        dispatched.set()
        stop, deadline = kw.get("cancel"), time.monotonic() + LIMIT
        while not (stop is not None and stop.is_set() or executor.cancels) and time.monotonic() < deadline:
            time.sleep(0.005)  # until Stop has landed, whichever way it reaches the executor
        return real_run(self, step_id, raw, **kw)

    monkeypatch.setattr(Session, "run", held_run)

    async def main():
        cfg = TurnConfig(approval_mode="auto")
        task = asyncio.create_task(run_turn(session, provider, ApprovalGate(ev), "go", [], cfg, ev))
        assert await asyncio.to_thread(dispatched.wait, LIMIT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, LIMIT)

    asyncio.run(main())
    step = session.data.steps[0]
    assert ran == [] and executor.cancels == 0  # the tool never ran, and no executor-wide cancel() was needed
    assert step.status == "error" and step.error.message == "stopped by the user"
    assert tool_entries(session) == {"c1": step.result_text}
    assert ev.of("turn.finished") == [{"reason": "stopped"}]


def test_stop_while_the_model_streams(tmp_path):
    class Chatty:
        actor = "agent:test"

        async def complete(self, messages, tools, on_delta):
            while True:
                on_delta("la ")
                await asyncio.sleep(0.001)

    session, _, ev = new_session(tmp_path)

    async def main():
        streaming = asyncio.Event()

        def emit(name, payload):
            ev(name, payload)
            if name == "message.delta":
                streaming.set()

        gate = ApprovalGate(emit)
        task = asyncio.create_task(run_turn(session, Chatty(), gate, "sing", [], TurnConfig(), emit))
        await asyncio.wait_for(streaming.wait(), LIMIT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, LIMIT)

    asyncio.run(main())
    assert ev.of("turn.finished") == [{"reason": "stopped"}]
    assert [m.role for m in session.data.messages] == ["user"]  # the half-streamed reply is dropped
    assert session.data.transcript == [{"role": "user", "content": "sing"}]


# Added beyond the brief's tests, for two defects found in self-review (see the task report).

def test_scripted_provider_deeply_nested_file(tmp_path):
    # "Any bad file is an EngineError with a hint": json.loads raises RecursionError, not ValueError, here.
    script = tmp_path / "script.json"
    script.write_text("[" * 100_000, encoding="utf-8")
    with pytest.raises(EngineError, match="can't read the fake provider script") as e:
        ScriptedProvider.from_file(script)
    assert e.value.hint


def test_a_stop_as_the_turn_opens_never_loses_the_users_changes(tmp_path):
    # Stop can land while the turn takes the user's changes (behind the server's lock that call can wait a
    # while). The call still runs, since every session call is shielded, so the model must still hear
    # those changes: spec §5.3, and "the model hears each change once".
    ev = Events()
    session = Session.new(emit=ev, output_dir=tmp_path)
    lincoln = session.import_image(LINCOLN, "lincoln")
    provider = ScriptedProvider([Reply(text="ok")])

    async def main():
        busy, free = asyncio.Event(), asyncio.Event()

        async def behind_the_lock(fn, *args):  # the server's `blocking` while the user's own call holds the lock
            if "turn.started" in ev.names() and not busy.is_set():  # the turn's first session call waits
                busy.set()
                await free.wait()
            return await asyncio.to_thread(fn, *args)

        task = asyncio.create_task(run_turn(session, provider, ApprovalGate(ev), "go", [], TurnConfig(), ev,
                                            behind_the_lock))
        await asyncio.wait_for(busy.wait(), LIMIT)
        task.cancel()
        free.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, LIMIT)

    asyncio.run(main())
    assert ev.of("turn.finished") == [{"reason": "stopped"}] and provider.received == []
    nxt = ScriptedProvider([Reply(text="ok")])
    assert turn(session, nxt, ev, text="again")[0] == "done"
    heard = [m["content"] for m in nxt.received[0][1:] if m["role"] == "system"]
    assert sum(f"{lincoln.id[:8]} (lincoln_work)" in note for note in heard) == 1  # heard, and once
    notes = [m.content[0].text for m in session.data.messages if m.role == "system_note"]
    assert heard == notes  # the chat shows what the model heard
