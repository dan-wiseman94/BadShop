"""Session edit, replay (remapping and the cache) and delete-last (spec 5.3, 6, 7; Review Focus 2 and 4)."""

import io
import json

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session.artifacts import short
from badshop.session.execution import InProcessExecutor, ToolOutcome
from badshop.session.models import Part, SessionData
from badshop.session.session import Session


class Counting:
    """An Executor that records which tools really ran. A tool named in `broken` fails, as a tool whose
    worker died would."""

    def __init__(self):
        self.inner = InProcessExecutor()
        self.calls: list[str] = []
        self.broken: set[str] = set()

    def run(self, call, cancel=None):
        self.calls.append(call.tool)
        if call.tool in self.broken:
            return ToolOutcome(False, error_message=f"the {call.tool} tool broke")
        return self.inner.run(call, cancel)

    def cancel(self):
        self.inner.cancel()

    def close(self):
        self.inner.close()


def _photo() -> bytes:
    """A 240x180 JPEG: its working copy (a PNG) is a different artifact from the original."""
    im = Image.new("RGB", (240, 180), (40, 90, 200))
    im.paste((250, 200, 40), (60, 40, 180, 140))
    im.paste((200, 30, 30), (100, 70, 140, 110))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


def _jpeg(rgb: tuple[int, int, int]) -> bytes:
    """A small one-colour JPEG: like _photo, it imports as a working copy with its original beside it."""
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), rgb).save(buf, "JPEG", quality=90)
    return buf.getvalue()


class Rig:
    def __init__(self, tmp_path):
        self.events: list[tuple[str, dict]] = []
        self.saves = 0
        self.ex = Counting()
        self.s = Session.new("replay test", executor=self.ex, output_dir=tmp_path / "out",
                             emit=lambda name, p: self.events.append((name, p)), on_change=self._saved)
        self.work = self.s.import_image(_photo(), "photo.jpg")

    def _saved(self):
        self.saves += 1

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def chain(self):
        """s1 invert -> s2 cutout of s1 -> s3 cutout of s2 -> s4 paste of s3's piece onto s2's piece
        (s4 reads two steps' outputs)."""
        s = self.s
        s1 = s.run_tool("filter", {"image": self.work.id, "names": ["invert"]}, "user")
        s2 = s.run_tool("cutout", {"image": s1.outputs[0], "box": [20, 20, 220, 180], "no_ai": True},
                        "agent:fake")
        s3 = s.run_tool("cutout", {"image": s2.outputs[0], "box": [100, 60, 180, 130], "no_ai": True},
                        "agent:fake")
        s4 = s.run_tool("paste", {"base": s2.outputs[0], "piece": s3.outputs[0], "at": [10, 10], "width": 40},
                        "agent:fake")
        assert [x.status for x in (s1, s2, s3, s4)] == ["done"] * 4
        self.ex.calls.clear()
        self.events.clear()
        s.take_changes()
        return s1, s2, s3, s4


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_edit_marks_the_step_and_later_steps_stale_without_running(rig):
    s1, s2, s3, s4 = rig.chain()
    rig.s.reject(rig.s.propose("filter", {"image": s4.outputs[0], "names": ["sepia"]}, "agent:fake").id)
    rig.events.clear()
    rig.s.take_changes()
    saves = rig.saves
    stale = rig.s.edit(s2.id, {"image": s1.outputs[0][:8], "box": [0, 0, 200, 150], "no_ai": True})
    assert [x.id for x in stale] == [s2.id, s3.id, s4.id]  # the rejected s5 is left alone
    assert [x.status for x in rig.s.data.steps] == ["done", "stale", "stale", "stale", "rejected"]
    assert s2.edited and s2.params["box"] == [0, 0, 200, 150]
    assert s2.params["image"] == s1.outputs[0]  # the short ref is stored as the full id
    assert rig.ex.calls == []  # nothing ran
    assert rig.events == [("step.stale", {"step_ids": [s2.id, s3.id, s4.id]})]
    assert rig.saves > saves
    [note] = rig.s.take_changes()
    assert note.startswith("the user edited step 2: cutout ")
    assert s1.outputs[0][:8] in note and s1.outputs[0] not in note  # short ids for the agent


def test_an_edit_that_changes_nothing_is_not_an_edit(rig):
    s1, s2, s3, s4 = rig.chain()
    stale = rig.s.edit(s2.id, {"image": s1.outputs[0], "box": [20, 20, 220, 180], "no_ai": True})
    assert [x.id for x in stale] == [s2.id, s3.id, s4.id]  # "Apply & replay" still replays
    assert not s2.edited and rig.s.take_changes() == []  # but the agent hears of no edit
    assert rig.events == [("step.stale", {"step_ids": [s2.id, s3.id, s4.id]})]
    rig.s.replay_from(s2.id)
    assert rig.ex.calls == [] and [x.status for x in rig.s.data.steps] == ["done"] * 4
    assert "(edited)" not in rig.s.summary()


def test_edit_refuses_bad_params_unknown_refs_and_later_images(rig):
    s1, s2, s3, s4 = rig.chain()
    before = [x.model_dump() for x in rig.s.data.steps]
    with pytest.raises(EngineError) as e:
        rig.s.edit(s2.id, {"image": s1.outputs[0], "box": [0, 0, 200], "no_ai": True})
    assert e.value.message == "bad parameters for cutout" and "box" in e.value.hint
    with pytest.raises(EngineError) as e:
        rig.s.edit(s2.id, {"image": "ffffff", "no_ai": True})
    assert e.value.message == "no such artifact: ffffff"
    with pytest.raises(EngineError) as e:  # s3's output comes from a later step
        rig.s.edit(s2.id, {"image": s3.outputs[0], "no_ai": True})
    assert e.value.message == f"step 2 can't use {s3.outputs[0][:8]}: step 3 makes it later"
    assert e.value.hint == "use an imported image or one an earlier step made"
    with pytest.raises(EngineError) as e:  # nor may a step use its own output
        rig.s.edit(s2.id, {"image": s2.outputs[0], "no_ai": True})
    assert e.value.message.endswith("it is this step's own output")
    with pytest.raises(EngineError):
        rig.s.edit("s99", {"image": s1.outputs[0]})
    assert [x.model_dump() for x in rig.s.data.steps] == before
    assert rig.events == [] and rig.s.take_changes() == []


def test_an_import_that_a_step_makes_again_is_still_the_users(rig):
    """prep of a working copy gives back the same bytes, so the import is also step 1's first output.
    It still counts as the import: step 1 can be edited while it reads it, and the steps after step 1
    follow what step 1 makes (the SKILL.md flow: import, prep, then work on prep's copy)."""
    s = rig.s
    s1 = s.run_tool("prep", {"image": rig.work.id}, "user")
    assert s1.outputs[0] == rig.work.id and s.artifacts.meta[rig.work.id].produced_by is None
    s2 = s.run_tool("filter", {"image": s1.outputs[0], "names": ["invert"]}, "agent:fake")
    stale = s.edit(s1.id, {"image": rig.work.id, "max": 120})
    assert [x.id for x in stale] == [s1.id, s2.id]
    s.replay_from(s1.id)
    small = s1.outputs[0]
    assert small != rig.work.id and s.artifacts.meta[small].width == 120
    assert s1.params["image"] == rig.work.id  # step 1 still reads the import
    assert s2.params["image"] == small and s2.status == "done"
    with pytest.raises(EngineError) as e:  # a picture step 1 made first is still its own output
        s.edit(s1.id, {"image": small, "max": 100})
    assert "it is this step's own output" in e.value.message


def test_replay_remaps_references_to_new_outputs(rig):
    s1, s2, s3, s4 = rig.chain()
    old = {x.id: list(x.outputs) for x in (s1, s2, s3, s4)}
    rig.s.edit(s1.id, {"image": rig.work.id, "names": ["grayscale"]})
    rig.events.clear()
    ran = rig.s.replay_from(s1.id)
    assert [x.id for x in ran] == [s1.id, s2.id, s3.id, s4.id]
    assert all(x.status == "done" and x.error is None for x in ran)
    assert rig.ex.calls == ["filter", "cutout", "cutout", "paste"]
    for x in (s1, s2, s3, s4):
        assert x.outputs != old[x.id] and x.outputs[0] in rig.s.artifacts
        assert all(o in rig.s.artifacts for o in old[x.id])  # replay never removes artifacts
    assert s1.params["image"] == rig.work.id  # the import did not change
    assert s2.params["image"] == s1.outputs[0]
    assert s3.params["image"] == s2.outputs[0]
    assert s4.params["base"] == s2.outputs[0] and s4.params["piece"] == s3.outputs[0]
    assert not s2.edited  # remapping is not a user edit
    assert rig.names().count("step.started") == 4 and rig.names().count("step.finished") == 4
    note = rig.s.take_changes()[-1]
    assert note.startswith(f"the user replayed steps 1 to 4; step 4 now gives {s4.outputs[0][:8]} (")


def test_the_cache_skips_steps_whose_inputs_did_not_change(rig):
    s1, s2, s3, s4 = rig.chain()
    old = [list(x.outputs) for x in (s1, s2, s3, s4)]
    # A different box that clamps to the same pixels: s2 runs again and makes a byte-identical piece,
    # so s3 and s4 get the same parameters as before and reuse their results.
    rig.s.edit(s2.id, {"image": s1.outputs[0], "box": [20, 20, 220, 999], "no_ai": True})
    rig.events.clear()
    ran = rig.s.replay_from(s2.id)
    assert [x.id for x in ran] == [s2.id, s3.id, s4.id]
    assert rig.ex.calls == ["cutout"]
    assert [list(x.outputs) for x in (s1, s2, s3, s4)] == old
    assert [x.status for x in rig.s.data.steps] == ["done"] * 4
    assert s3.cache_key and s3.result_text  # the reused result keeps its text
    assert rig.names() == ["step.started", "step.finished", "step.finished", "step.finished"]
    reused = rig.events[-1][1]
    assert reused["step"]["id"] == s4.id and reused["step"]["status"] == "done"
    assert [a["id"] for a in reused["artifacts"]] == s4.outputs


def test_replay_of_unchanged_steps_runs_nothing_unless_the_cache_is_off(rig):
    steps = rig.chain()
    ids = [x.id for x in steps]
    old = [list(x.outputs) for x in steps]
    saves = rig.saves
    assert [x.id for x in rig.s.replay_from(steps[0].id)] == ids
    assert rig.ex.calls == [] and [x.status for x in steps] == ["done"] * 4
    assert rig.events[0] == ("step.stale", {"step_ids": ids})  # done steps go stale first, then come back
    assert rig.names()[1:] == ["step.finished"] * 4
    assert rig.saves > saves
    # Without the cache every step really runs, and the engine makes the same bytes (spec 2, criterion 4).
    rig.s.replay_from(steps[0].id, use_cache=False)
    assert rig.ex.calls == ["filter", "cutout", "cutout", "paste"]
    assert [list(x.outputs) for x in steps] == old


def test_a_cached_result_whose_artifacts_are_gone_is_rerun(rig):
    s1, s2, s3, s4 = rig.chain()
    gone = s4.outputs[0]
    rig.s.artifacts.drop([gone])
    assert gone not in rig.s.artifacts
    rig.s.replay_from(s4.id)
    assert rig.ex.calls == ["paste"]
    assert s4.outputs == [gone] and gone in rig.s.artifacts  # the same pixels again


def test_a_missing_input_fails_the_step_instead_of_the_replay(rig):
    s1, s2, s3, s4 = rig.chain()
    d = s4.outputs[0]
    rig.s.artifacts.drop([s3.outputs[0]])  # s4's piece
    ran = rig.s.replay_from(s4.id, use_cache=False)
    assert [x.id for x in ran] == [s4.id]
    assert s4.status == "error" and "no such artifact" in s4.error.message
    assert s4.outputs == [] and s4.previous_outputs == [d]
    assert rig.names()[-1] == "step.failed"
    assert [x.status for x in (s1, s2, s3)] == ["done"] * 3


def test_an_edit_that_breaks_a_later_step_stops_the_replay_there(rig):
    """Review Focus 4: a smaller piece puts s3's box off the image. Replay stops at s3, s4 stays stale,
    earlier outputs are intact, and fixing s3 replays the rest. s4 reads both s2's piece (made before
    the failure) and s3's piece (made after the fix), and ends up on the new ones."""
    s1, s2, s3, s4 = rig.chain()
    a, c, d = s1.outputs[0], s3.outputs[0], s4.outputs[0]
    key4 = s4.cache_key
    rig.s.edit(s2.id, {"image": a, "box": [20, 20, 100, 80], "no_ai": True})  # an 80x60 piece
    rig.events.clear()
    ran = rig.s.replay_from(s2.id)
    assert [x.id for x in ran] == [s2.id, s3.id]
    assert rig.ex.calls == ["cutout", "cutout"]
    assert [x.status for x in rig.s.data.steps] == ["done", "done", "error", "stale"]
    b = s2.outputs[0]
    assert s1.outputs == [a] and a in rig.s.artifacts  # earlier outputs intact
    assert rig.s.artifacts.meta[b].width == 80
    assert "empty or lies outside" in s3.error.message and s3.error.hint
    assert s3.params["image"] == b  # the failed step ran on the new piece
    assert s3.outputs == [] and s3.previous_outputs == [c]  # what s4 still points at
    # s4 did not run: it keeps its last result, but already reads s2's new piece; its piece waits for s3
    assert (s4.params["base"], s4.params["piece"]) == (b, c)
    assert s4.outputs == [d] and s4.cache_key == key4
    assert rig.names()[-1] == "step.failed"
    assert "step 3 (cutout) failed" in rig.s.take_changes()[-1]
    with pytest.raises(EngineError) as e:  # s4 can't be replayed on its own while s3 is broken
        rig.s.replay_from(s4.id)
    assert "step 3 (cutout)" in e.value.message and "replay from step 3" in e.value.hint

    stale = rig.s.edit(s3.id, {"image": b, "box": [10, 10, 70, 50], "no_ai": True})
    assert [x.id for x in stale] == [s3.id, s4.id]
    ran = rig.s.replay_from(s3.id)
    assert [x.id for x in ran] == [s3.id, s4.id]
    assert [x.status for x in rig.s.data.steps] == ["done"] * 4
    assert s3.previous_outputs == [] and s3.outputs[0] != c
    assert s4.params["base"] == s2.outputs[0] == b  # s2's new piece, not the one from before the edit
    assert s4.params["piece"] == s3.outputs[0]  # remapped from c, the output s3 had before it failed
    assert s4.outputs[0] != d


def test_a_failed_replay_survives_a_round_trip_of_the_session_data(rig):
    s1, s2, s3, s4 = rig.chain()
    c = s3.outputs[0]
    rig.s.edit(s2.id, {"image": s1.outputs[0], "box": [20, 20, 100, 80], "no_ai": True})
    rig.s.replay_from(s2.id)
    data = SessionData.model_validate(rig.s.data.model_dump(mode="json", by_alias=True))
    again = Session(data, rig.s.artifacts, executor=rig.ex, output_dir=rig.s.output_dir)
    assert again.step(s3.id).previous_outputs == [c]
    again.edit(s3.id, {"image": again.step(s2.id).outputs[0], "box": [10, 10, 70, 50], "no_ai": True})
    again.replay_from(s3.id)
    assert again.step(s4.id).params["piece"] == again.step(s3.id).outputs[0] != c
    assert again.step(s4.id).params["base"] == again.step(s2.id).outputs[0]


def test_a_stopped_replay_leaves_a_reader_on_the_newest_step_that_made_its_picture(rig):
    """s3 makes the same picture as s1, so s4 reads s3's copy. When the replay stops at s2, s4 is not
    moved to s1's new picture: it keeps s3's, and s3 and s4 are reused once s2 works again."""
    s, w = rig.s, rig.work.id
    s1 = s.run_tool("cutout", {"image": w, "box": [0, 0, 200, 160], "no_ai": True}, "user")
    a = s1.outputs[0]
    s2 = s.run_tool("cutout", {"image": a, "box": [150, 100, 200, 150], "no_ai": True}, "user")
    s3 = s.run_tool("cutout", {"image": w, "box": [0, 0, 200, 160], "no_ai": True}, "user")
    s4 = s.run_tool("cutout", {"image": a, "box": [0, 0, 50, 50], "no_ai": True}, "user")
    c = s4.outputs[0]
    assert s3.outputs == [a]
    s.edit(s1.id, {"image": w, "box": [0, 0, 100, 80], "no_ai": True})
    s.replay_from(s1.id)
    assert [x.status for x in s.data.steps] == ["done", "error", "stale", "stale"]
    assert s2.params["image"] == s1.outputs[0] != a  # s2 read s1's new picture, and its box is off it
    assert s4.params["image"] == a  # still s3's picture
    s.edit(s2.id, {"image": s1.outputs[0], "box": [10, 10, 50, 50], "no_ai": True})
    rig.ex.calls.clear()
    s.replay_from(s2.id)
    assert rig.ex.calls == ["cutout"]  # s3 and s4 asked what they asked before
    assert [x.status for x in s.data.steps] == ["done"] * 4
    assert s4.params["image"] == s3.outputs[0] == a and s4.outputs == [c]


def test_a_failed_step_still_stands_for_what_it_made(rig):
    """s2 (prep) gives s1's picture back, so s3 reads s2's copy. When s2 fails in a replay, s3 waits for
    s2 instead of taking s1's new picture, and follows s2 once it works again."""
    s, w = rig.s, rig.work.id
    s1 = s.run_tool("filter", {"image": w, "names": ["invert"]}, "user")
    a = s1.outputs[0]
    s2 = s.run_tool("prep", {"image": a}, "user")
    assert s2.outputs[0] == a
    s3 = s.run_tool("filter", {"image": a, "names": ["sepia"]}, "user")
    rig.ex.broken.add("prep")
    s.edit(s1.id, {"image": w, "names": ["grayscale"]})
    s.replay_from(s1.id)
    assert [x.status for x in s.data.steps] == ["done", "error", "stale"]
    assert s2.error.message == "the prep tool broke" and s2.previous_outputs[0] == a
    assert s3.params["image"] == a  # waits for s2
    rig.ex.broken.clear()
    s.edit(s2.id, {"image": s1.outputs[0], "max": 100})
    s.replay_from(s2.id)
    assert [x.status for x in s.data.steps] == ["done"] * 3
    assert s.artifacts.meta[s2.outputs[0]].width == 100
    assert s3.params["image"] == s2.outputs[0] != s1.outputs[0]  # s2's 100 px copy, not s1's picture


def test_replay_refuses_to_start_after_a_stale_step(rig):
    s1, s2, s3, s4 = rig.chain()
    rig.s.edit(s2.id, {"image": s1.outputs[0], "box": [0, 0, 200, 150], "no_ai": True})
    with pytest.raises(EngineError) as e:
        rig.s.replay_from(s3.id)
    assert "step 2 (cutout) comes first" in e.value.message and "replay from step 2" in e.value.hint
    assert rig.ex.calls == [] and [x.status for x in (s2, s3, s4)] == ["stale"] * 3


def test_replay_skips_rejected_steps_and_refuses_waiting_ones(rig):
    s1, s2, s3, s4 = rig.chain()
    s5 = rig.s.propose("filter", {"image": s4.outputs[0], "names": ["sepia"]}, "agent:fake")
    rig.s.reject(s5.id)
    rig.s.edit(s4.id, {"base": rig.work.id, "piece": s3.outputs[0], "at": [30, 30], "width": 40})
    rig.s.replay_from(s4.id)
    assert rig.ex.calls == ["paste"] and s5.status == "rejected" and s5.outputs == []

    s6 = rig.s.propose("filter", {"image": s4.outputs[0], "names": ["sepia"]}, "agent:fake")
    blur = {"image": rig.work.id, "names": ["blur"]}
    for call in (lambda: rig.s.replay_from(s1.id), lambda: rig.s.edit(s1.id, blur),
                 lambda: rig.s.edit(s6.id, blur)):
        with pytest.raises(EngineError) as e:
            call()
        assert "waiting for approval" in e.value.message and "approve or reject" in e.value.hint
    assert s1.status == "done" and s6.status == "proposed"


def test_byte_identical_outputs_keep_their_first_producer(rig):
    """Review Focus 2: two steps make the same artifact. It keeps its first produced_by, a reader follows
    the newest step before it that made the artifact, and replaying or deleting either step never
    removes an artifact another step or a message still references."""
    s = rig.s
    s1 = s.run_tool("filter", {"image": rig.work.id, "names": ["invert"]}, "user")
    s2 = s.run_tool("filter", {"image": rig.work.id, "names": ["invert"]}, "agent:fake")
    a = s1.outputs[0]
    assert s2.outputs == [a] and s.artifacts.meta[a].produced_by == s1.id
    s3 = s.run_tool("cutout", {"image": a, "box": [0, 0, 120, 90], "no_ai": True}, "agent:fake")
    c = s3.outputs[0]
    s.add_message("assistant", [Part(type="text", text="look"), Part(type="image", artifact_id=a)],
                  [s2.id, s3.id])

    # s1 changes but s2 still makes a, so s3 (after s2) keeps reading a
    s.edit(s1.id, {"image": rig.work.id, "names": ["grayscale"]})
    rig.ex.calls.clear()
    s.replay_from(s1.id)
    g = s1.outputs[0]
    assert rig.ex.calls == ["filter"]  # s2 and s3 asked what they asked before
    assert s2.outputs == [a] and s3.params["image"] == a and s3.outputs == [c]
    assert g != a and s.artifacts.meta[g].produced_by == s1.id
    assert a in s.artifacts and s.artifacts.meta[a].produced_by == s1.id  # still its first producer

    # s2 changes too: now s3 follows s2's new picture, and a stays for the message that shows it
    s.edit(s2.id, {"image": rig.work.id, "names": ["sepia"]})
    s.replay_from(s2.id)
    p, c2 = s2.outputs[0], s3.outputs[0]
    assert s3.params["image"] == p and s3.outputs != [c]
    assert s.artifacts.meta[p].produced_by == s2.id
    assert a in s.artifacts and {a, g, p} <= s.referenced_ids()

    s.delete_last(s3.id)
    s.delete_last(s2.id)
    assert [x.id for x in s.data.steps] == [s1.id]
    assert a in s.artifacts and a in s.referenced_ids()  # the message still shows it
    # The message still names s2 and s3, so what they made first stays for the chat after they are
    # deleted: p, and s3's pieces from before and after the replay. A save keeps them too.
    assert all(x in s.artifacts for x in (p, c, c2)) and {p, c, c2} <= s.referenced_ids()
    # Deleting rewrites no record: the message still lists s2 and s3 and p is still credited to s2,
    # which is what keeps both ids from coming back.
    assert s.data.messages[-1].step_ids == [s2.id, s3.id]
    assert s.artifacts.meta[p].produced_by == s2.id and s.artifacts.meta[a].produced_by == s1.id
    assert s.propose("view", {"image": g}, "agent:fake").id == "s4"


def test_a_step_can_take_another_steps_result(rig):
    s = rig.s
    s1 = s.run_tool("filter", {"image": rig.work.id, "names": ["invert"]}, "user")
    s2 = s.run_tool("filter", {"image": rig.work.id, "names": ["grayscale"]}, "user")
    a, g = s1.outputs[0], s2.outputs[0]
    s.edit(s1.id, {"image": rig.work.id, "names": ["grayscale"]})
    rig.ex.calls.clear()
    s.replay_from(s1.id)
    assert rig.ex.calls == []  # s1 now asks exactly what s2 asked, so s2's result is reused
    assert s1.outputs == [g] and s2.outputs == [g] and s.artifacts.meta[g].produced_by == s2.id
    s.delete_last(s2.id)
    assert s1.outputs == [g] and s.artifacts.meta[g].produced_by == s2.id  # the first producer, deleted
    assert a in s.artifacts and a not in s.referenced_ids()
    assert s.propose("view", {"image": g}, "user").id == "s3"  # g still names s2


def test_delete_last_only_deletes_the_last_finished_step(rig):
    s1, s2, s3, s4 = rig.chain()
    saves = rig.saves
    with pytest.raises(EngineError) as e:
        rig.s.delete_last(s3.id)
    assert "only the last step" in e.value.message and "step 4" in e.value.hint
    assert len(rig.s.data.steps) == 4 and rig.events == []
    rig.s.delete_last(s4.id)
    assert [x.id for x in rig.s.data.steps] == [s1.id, s2.id, s3.id]
    assert rig.events == [("step.deleted", {"step_id": s4.id})]  # every client drops the step's card
    assert s4.outputs[0] in rig.s.artifacts
    assert rig.s.artifacts.meta[s4.outputs[0]].produced_by == s4.id
    assert rig.s.take_changes() == ["the user deleted step 4 (paste)"]
    assert rig.saves > saves
    s5 = rig.s.propose("filter", {"image": s3.outputs[0], "names": ["sepia"]}, "agent:fake")
    assert (s5.id, s5.index) == ("s5", 4)  # a new id: s4's picture still names s4
    with pytest.raises(EngineError) as e:
        rig.s.delete_last(s5.id)
    assert "waiting for approval" in e.value.message
    with pytest.raises(EngineError):
        rig.s.delete_last("s99")
    assert rig.names() == ["step.deleted", "step.proposed"]  # a refused delete emits nothing


def test_referenced_ids(rig):
    s = rig.s
    lone = s.import_image(_png(), "lone.png")  # imported but never used: a save still keeps it
    s1 = s.run_tool("filter", {"image": rig.work.id, "names": ["invert"]}, "user")
    s.add_message("user", [Part(type="image", artifact_id=s1.outputs[0])])
    ids = s.referenced_ids()
    assert ids == {rig.work.id, rig.work.original_id, s1.outputs[0], lone.id}
    assert lone.id in ids and lone.original_id is None and rig.work.original_id != rig.work.id


def test_referenced_ids_keep_what_the_chat_and_the_model_point_at(rig):
    """A deleted step that a message names keeps its picture, and so does every artifact whose short id
    the transcript or a message's text mentions: a reopened session never loses a picture the chat or
    the model still points at (Review Focus 2, the save side)."""
    s = rig.s
    s1 = s.run_tool("filter", {"image": rig.work.id, "names": ["invert"]}, "user")
    s2 = s.run_tool("filter", {"image": s1.outputs[0], "names": ["sepia"]}, "agent:fake")
    s.add_message("assistant", [Part(type="text", text="sepia it is")], [s2.id])
    s3 = s.run_tool("cutout", {"image": s2.outputs[0], "box": [0, 0, 120, 90], "no_ai": True}, "user")
    y, z = s2.outputs[0], s3.outputs[0]
    told, said, shown, glued, lone = (s.import_image(_jpeg(rgb), f"{name}.jpg") for name, rgb in (
        ("told", (200, 0, 0)), ("said", (0, 200, 0)), ("shown", (0, 0, 200)), ("glued", (200, 200, 0)),
        ("lone", (90, 90, 90))))
    assert all(m.original_id not in (None, m.id) for m in (told, said, shown, glued, lone))
    # The transcript in the provider format Task 11 writes: a system note, then a tool call whose
    # arguments are a JSON string, then its result. deadbeef is no artifact's short id, and glued's
    # short id counts even though it sits inside a longer run of hex digits.
    s.data.transcript.extend([
        {"role": "system", "content": f"the user added image {short(told.id)} (told)"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "view", "arguments": json.dumps({"image": short(said.id)})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": f"not run: no picture deadbeef{short(glued.id)}"},
    ])
    s.add_message("assistant", [Part(type="text", text=f"compare it with {shown.id}")])  # a full id
    s.delete_last(s3.id)
    s.delete_last(s2.id)
    ids = s.referenced_ids()
    assert y in ids  # s2 is deleted, but a message still names it
    assert z not in ids and z in s.artifacts  # nothing names s3 or mentions its piece: dropped at save
    assert lone.id in ids and lone.original_id in ids  # nothing names it, but the user imported it
    assert ids == {rig.work.id, rig.work.original_id, s1.outputs[0], y, told.id, told.original_id,
                   said.id, said.original_id, shown.id, shown.original_id, glued.id, glued.original_id,
                   lone.id, lone.original_id}


def test_referenced_ids_keep_a_deleted_steps_picture_only_while_something_mentions_it(rig):
    """The mention half of R6 on step outputs, which (unlike the user's imports) nothing else keeps once
    their step is deleted: a short id in a tool call's arguments or inside a longer hex run in a tool
    result, or a full id in a message's text, keeps the picture; a picture nothing mentions is dropped."""
    s = rig.s
    steps = [s.run_tool("filter", {"image": rig.work.id, "names": [name]}, "agent:fake")
             for name in ("invert", "sepia", "grayscale", "emboss", "edges")]
    live, called, told, written, dropped = (st.outputs[0] for st in steps)
    s.data.transcript.extend([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "view", "arguments": json.dumps({"image": short(called)})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": f"not run: no picture deadbeef{short(told)}"},
    ])
    s.add_message("assistant", [Part(type="text", text=f"compare it with {written}")])
    for st in reversed(steps[1:]):
        s.delete_last(st.id)
    assert all(x in s.artifacts for x in (called, told, written, dropped))
    assert s.referenced_ids() == {rig.work.id, rig.work.original_id, live, called, told, written}
