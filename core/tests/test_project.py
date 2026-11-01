import hashlib
import io
import json
import os
import stat
import struct
import tracemalloc
import zipfile
from pathlib import Path, PurePosixPath

import pytest
from PIL import Image

from badshop.cli import main as cli
from badshop.cli.argparse_gen import to_argv
from badshop.engine.errors import EngineError
from badshop.session import project
from badshop.session.artifacts import short
from badshop.session.models import Part, Step
from badshop.session.session import Session
from badshop.tools.registry import REGISTRY, get
from badshop.tools.runner import validate
from conftest import FIXTURES

# --- to_argv: a step's params as the command a person would type ---

# Every field of every tool set away from its default, with the awkward values a model or user may give:
# negative numbers, exponent floats, words that start with "-", new lines and non-ASCII text.
RICH = {
    "layout": {"template": "comic", "images": ["a.png"], "image_slots": [1], "title": "A story", "captions": ["one", "two"], "slots": [[30, 120, 470, 480], [520, 120, 960, 480]], "fit": "stretch", "background": "red", "accent": "blue"},
    "pair_images": {"donors": ["a.png"], "backgrounds": ["b.png"], "role": "head", "side": "left", "target_box": [10, 20, 100, 140], "n": 2},
    "slice_sheet": {"image": "a.png", "rows": 2, "columns": 3, "margins": [1, 2, 3, 4], "gap": [2, 3], "cells": [0, 4]},
    "discover": {"query": "Lincoln", "source": "commons", "n": 4, "purpose": "head", "pose": "facing left", "expression": "smiling", "same_subject": True, "similar_to": "a.png", "reference_url": "https://example.org/thumb", "variation": "different", "exclude_urls": ["https://example.org/old"]},
    "acquire": {"url": "https://example.org/image", "source_kind": "commons", "page": "https://example.org/page", "title": "Portrait", "license": "CC0", "creator": "Painter"},
    "fetch": {"query": "-dog sitting", "source": "openverse", "n": 3, "clipboard": True},
    "wiki": {"title": "Abraham Lincoln", "n": 2, "lang": "de"},
    "emoji": {"emoji": ["😂", "skull", "1f480"], "size": 144},
    "template": {"name": "drake", "n": 2, "list_all": True},
    "info": {"image": "a.png"},
    "prep": {"image": "a.png", "max": 500},
    "view": {"image": "a.png", "grid": True, "max": 512},
    "find": {"image": "a.png", "what": "cats", "detector": "haar", "min_score": 0.35},
    "text": {"image": "a.png", "text": "-_- WHEN\nTHE CODE ✓", "style": "wordart", "bottom": True, "at": [-5, 300],
             "size": 48, "color": "#ff00ff", "rotate": -1e-05, "margin": 0, "font": "ComicNeue-Bold.ttf"},
    "cutout": {"image": "a.png", "box": [10, 20, 110, 220], "model": "isnet-anime", "threshold": 200, "grow": 3,
               "no_ai": True, "oval": True, "sticker": 4, "sticker_color": "black"},
    "paste": {"base": "a.png", "piece": "b.png", "at": [-10, 20], "anchor": "bottom", "width": 120.5,
              "height": 80.0, "fit_box": [1, 2, 3, 4], "scale": 1.3, "rotate": -12.5, "flip": True, "repeat": 5,
              "region": [0, 0, 50, 50], "seed": -3},
    "draw": {"image": "a.png", "circle": [[10, 10, 5], [-1, -2, 3]], "arrow": [[0, 0, 10, 10]],
             "line": [[5, 5, -5, -5]], "rect": [[1, 1, 9, 9], [2, 2, 8, 8]], "color": "blue", "width": 2},
    "censor": {"image": "a.png", "box": [[1, 2, 3, 4], [5, 6, 7, 8]], "style": "bar", "block": 4},
    "eyes": {"image": "a.png", "at": [[260, 240], [300, -240]], "angle": -30.0, "size": 7, "color": "lime"},
    "filter": {"image": "a.png", "names": ["emboss", "invert", "emboss"]},
    "warp": {"image": "a.png", "at": [[10, 10, 5]], "strength": -0.5},
    "flare": {"image": "a.png", "at": [-3, 4], "size": 9},
    "sparkle": {"image": "a.png", "at": [[1, 2]], "repeat": 7, "region": [0, 0, 9, 9], "size": 3, "color": "gold",
                "seed": 42},
    "watermark": {"image": "a.png", "names": ["hypercam", "ifunny"], "text": "-made in badshop-", "corner": "tl"},
    "save": {"image": "a.png", "quality": 5, "passes": 3, "lowres": 0.3, "gif": True, "colors": 16,
             "name": "lincoln_final"},
    "deepfry": {"image": "a.png", "level": 5, "no_tint": True, "seed": 0, "name": "fried"},
    "animate": {"images": ["a.png", "b.png"], "effect": "zoom", "frames": 9, "delay": 120, "amount": 2.5,
                "at": [5, 6], "hold": 0, "fry": 2, "colors": 32, "seed": 9, "name": "zoomy"},
    "export": {"image": "a.png", "name": "keep"},
}


def png_bytes(size: tuple[int, int], color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def dumped(tool: str, raw: dict) -> dict:
    """What a step stores: validated params, JSON-safe."""
    return validate(tool, raw).model_dump(mode="json")


def parsed(argv: list[str]) -> tuple[str, dict]:
    """What the CLI does with argv: the subcommand and the raw params it hands to the tool."""
    a = cli.build_parser().parse_args(argv)
    return a.cmd, {k: v for k, v in vars(a).items() if k not in ("cmd", "_tool", "_out")}


def test_every_tool_has_a_rich_sample():
    assert set(RICH) == {name for name in REGISTRY if not name.startswith("_")}  # "_x": test-only tools
    for tool, raw in RICH.items():
        model = get(tool).params
        assert set(raw) == set(model.model_fields), tool
        params = validate(tool, raw)
        for name, f in model.model_fields.items():
            if not f.is_required():
                assert getattr(params, name) != f.get_default(call_default_factory=True), (tool, name)


@pytest.mark.parametrize("variant", ["rich", "required only"])
@pytest.mark.parametrize("tool", sorted(RICH))
def test_to_argv_round_trips_through_the_cli_parser(tool, variant):
    spec = get(tool)
    raw = RICH[tool] if variant == "rich" else {
        k: v for k, v in RICH[tool].items() if spec.params.model_fields[k].is_required()}
    argv = to_argv(spec, dumped(tool, raw))
    cmd, back = parsed(argv)
    assert argv[0] == cmd == tool
    assert validate(tool, back) == validate(tool, raw)


def test_to_argv_writes_what_a_person_would_type():
    assert to_argv(get("prep"), dumped("prep", {"image": "a.png"})) == ["prep", "a.png"]
    assert to_argv(get("paste"), dumped("paste", {"base": "a.png", "piece": "b.png", "fit_box": [1, 2, 30, 40],
                                                  "scale": 1.1, "seed": -3})) == [
        "paste", "a.png", "b.png", "--fit-box", "1", "2", "30", "40", "--scale", "1.1", "--seed=-3"]
    assert to_argv(get("draw"), dumped("draw", {"image": "a.png", "circle": [[1, 2, 3], [4, -5, 6]]})) == [
        "draw", "a.png", "--circle", "1", "2", "3", "--circle", "4", "-5", "6"]
    assert to_argv(get("template"), dumped("template", {"name": "drake", "n": 2, "list_all": True})) == [
        "template", "drake", "-n", "2", "--list"]
    assert to_argv(get("watermark"), dumped("watermark", {"image": "a.png", "names": ["hypercam", "ifunny"]})) == [
        "watermark", "a.png", "hypercam", "ifunny"]
    # A positional word that starts with "-" goes after "--", every flag before it.
    assert to_argv(get("text"), dumped("text", {"image": "a.png", "text": "-_-", "size": 40})) == [
        "text", "--size", "40", "--", "a.png", "-_-"]


# --- sessions to save: a small meme made in-process ---


def meme(tmp_path: Path) -> Session:
    """Import lincoln and trump (both attached to a message), then five local edits by user and agent."""
    s = Session.new("lincoln meme", output_dir=tmp_path / "exports")
    work = s.import_image((FIXTURES / "lincoln.png").read_bytes(), "lincoln.png")
    trump = s.import_image((FIXTURES / "trump.png").read_bytes(), "trump.png")
    s.add_message("user", [Part(type="text", text="put trump's head on lincoln"),
                           Part(type="image", artifact_id=work.id), Part(type="image", artifact_id=trump.id)])
    inverted = s.run_tool("filter", {"image": work.id, "names": ["invert"]}, "user")
    head = s.run_tool("cutout", {"image": trump.id, "box": [150, 60, 330, 300], "oval": True}, "agent:fake")
    pasted = s.run_tool("paste", {"base": inverted.outputs[0], "piece": head.outputs[0],
                                  "fit_box": [140, 60, 320, 290], "scale": 1.1}, "agent:fake")
    s.run_tool("deepfry", {"image": pasted.outputs[0], "level": 2, "seed": 7}, "user")
    s.run_tool("animate", {"images": [inverted.outputs[0], pasted.outputs[0]], "delay": 200}, "user")
    assert [st.status for st in s.data.steps] == ["done"] * 5
    return s


def art(s: Session, aid: str) -> str:
    return f"artifacts/{aid}{s.artifacts.meta[aid].ext}"


def snapshot(s: Session) -> tuple[dict, dict]:
    return s.data.model_dump(mode="json", by_alias=True), {aid: s.artifacts.data(aid) for aid in s.artifacts.ids()}


def test_export_recipe_keeps_only_finished_local_edits(tmp_path):
    s = meme(tmp_path)
    inverted, head, pasted, fried, gif = (st.outputs[0] for st in s.data.steps)
    work, trump = s.data.steps[0].params["image"], s.data.steps[1].params["image"]
    s.run_tool("view", {"image": pasted, "grid": True}, "agent:fake")  # a look: not an edit
    s.run_tool("export", {"image": fried, "name": "keep"}, "user")  # writes a file: not an edit
    s.reject(s.propose("draw", {"image": pasted, "circle": [[10, 10, 5]]}, "agent:fake").id, "no circles")
    assert s.run_tool("cutout", {"image": pasted, "box": [50, 50, 50, 50], "no_ai": True}, "user").status == "error"
    s.data.steps.append(Step(id="s99", index=99, tool="wiki", params=dumped("wiki", {"title": "Abraham Lincoln"}),
                             actor="user", status="done", outputs=[work]))  # a network source: not an edit
    assert project.export_recipe(s) == {"vars": {}, "steps": [
        ["filter", art(s, work), "invert", "-o", art(s, inverted)],
        ["cutout", art(s, trump), "--box", "150", "60", "330", "300", "--oval", "-o", art(s, head)],
        ["paste", art(s, inverted), art(s, head), "--fit-box", "140", "60", "320", "290", "--scale", "1.1",
         "-o", art(s, pasted)],
        ["deepfry", art(s, pasted), "--level", "2", "--seed", "7", "-o", art(s, fried)],
        ["animate", art(s, inverted), art(s, pasted), "--delay", "200", "-o", art(s, gif)],
    ]}
    assert art(s, fried).endswith(".jpg") and art(s, gif).endswith(".gif")


def test_the_recipe_rebuilds_the_same_artifacts_with_the_cli(tmp_path, monkeypatch, capsys):
    s = meme(tmp_path)
    pasted = s.data.steps[2].outputs[0]
    s.run_tool("text", {"image": pasted, "text": "-_-", "size": 40}, "user")  # a step that needs "--"
    path = project.save(s, tmp_path / "meme")
    unzipped = tmp_path / "unzipped"
    with zipfile.ZipFile(path) as zf:
        zf.extractall(unzipped)  # our own file, just written
    recipe = json.loads((unzipped / "recipe.json").read_text(encoding="utf-8"))
    rebuilt = [argv[argv.index("-o") + 1] for argv in recipe["steps"]]
    assert len(rebuilt) == 6
    assert recipe["steps"][5] == ["text", "--size", "40", "-o", rebuilt[5], "--", art(s, pasted), "-_-"]
    for rel in rebuilt:
        (unzipped / rel).unlink()
    monkeypatch.chdir(unzipped)
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "final"))
    assert cli.main(["run", "recipe.json"]) == 0
    assert "== step 6/6" in capsys.readouterr().out
    for rel in rebuilt:
        assert hashlib.sha256((unzipped / rel).read_bytes()).hexdigest() == PurePosixPath(rel).stem


# --- save and open ---


def test_save_then_open_restores_the_session_exactly(tmp_path):
    s = meme(tmp_path)
    unused = s.import_image(png_bytes((40, 30), "orange"), "orange.png")  # never used by a step or message
    path = project.save(s, tmp_path / "meme")
    assert path == tmp_path / "meme.badshop" and path.is_file()
    keep = s.referenced_ids()
    assert unused.id in keep and unused.id in s.artifacts  # the user imported it: a save keeps it
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        payload = json.loads(zf.read("session.json"))
        recipe = json.loads(zf.read("recipe.json"))
    assert names == {"session.json", "recipe.json"} | {art(s, aid) for aid in keep}
    assert payload["schema"] == 2 and "schema_" not in payload and set(payload["artifacts"]) == keep
    assert recipe == project.export_recipe(s)

    reopened = project.open_project(path, output_dir=tmp_path / "exports")
    expected = s.data.model_dump(mode="json", by_alias=True)
    expected["artifacts"] = {aid: s.artifacts.meta[aid].model_dump(mode="json") for aid in keep}
    assert reopened.data.model_dump(mode="json", by_alias=True) == expected
    assert set(reopened.artifacts.ids()) == keep
    assert all(reopened.artifacts.data(aid) == s.artifacts.data(aid) for aid in keep)
    assert reopened.output_dir == tmp_path / "exports"


def test_a_deleted_steps_picture_the_chat_still_points_at_is_saved_and_reopened(tmp_path):
    # Review Focus 2, the save side (ruling R6): delete_last leaves a step's pictures in the store, and save
    # keeps them while a message's step_ids name the step or the transcript mentions the picture's short
    # id, so a reopened session never loses a picture the chat or the model still points at.
    s = meme(tmp_path)
    work = s.data.steps[0].params["image"]
    shown = s.run_tool("filter", {"image": work, "names": ["emboss"]}, "agent:fake")
    s.add_message("assistant", [Part(type="text", text="embossed it")], [shown.id])  # the chat names it
    told = s.run_tool("filter", {"image": work, "names": ["sepia"]}, "agent:fake")
    s.data.transcript.extend([  # the model heard of it: a call and its result, as the agent loop records them
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "filter", "arguments": json.dumps({"image": short(work), "names": ["sepia"]})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": told.result_text},
    ])
    dropped = s.run_tool("filter", {"image": work, "names": ["edges"]}, "agent:fake")  # nothing points at it
    pictures = {st.id: st.outputs[0] for st in (shown, told, dropped)}
    assert all(s.artifacts.meta[aid].produced_by == sid for sid, aid in pictures.items())
    assert short(pictures[told.id]) in told.result_text
    for st in (dropped, told, shown):  # the last step each time
        s.delete_last(st.id)
    assert [st.tool for st in s.data.steps] == ["filter", "cutout", "paste", "deepfry", "animate"]
    assert all(aid in s.artifacts for aid in pictures.values())  # delete_last removes no artifact
    keep = s.referenced_ids()
    assert pictures[shown.id] in keep and pictures[told.id] in keep and pictures[dropped.id] not in keep

    path = project.save(s, tmp_path / "meme")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert art(s, pictures[shown.id]) in names and art(s, pictures[told.id]) in names
    assert art(s, pictures[dropped.id]) not in names  # save still drops what nothing points at

    reopened = project.open_project(path, output_dir=tmp_path / "exports")
    assert [st.tool for st in reopened.data.steps] == ["filter", "cutout", "paste", "deepfry", "animate"]
    assert reopened.data.messages[-1].step_ids == [shown.id]
    for sid in (shown.id, told.id):  # the deleted steps' pictures are back, still credited to them
        aid = pictures[sid]
        assert reopened.artifacts.data(aid) == s.artifacts.data(aid)
        assert reopened.artifacts.meta[aid].produced_by == sid
    assert pictures[dropped.id] not in reopened.artifacts
    assert reopened.artifacts.resolve(short(pictures[told.id])) == pictures[told.id]  # the id the model has
    assert reopened.referenced_ids() == keep  # so the next save or autosave keeps them too


def test_a_reopened_session_replays_to_the_same_pixels(tmp_path):
    # spec §2 criterion 4 and §11: save -> open -> replay gives byte-identical artifacts
    s = meme(tmp_path)
    before = [list(st.outputs) for st in s.data.steps]
    reopened = project.open_project(project.save(s, tmp_path / "meme"), output_dir=tmp_path / "exports")
    reopened.artifacts.drop([aid for outs in before for aid in outs])  # nothing to reuse: every step really runs
    ran = reopened.replay_from(reopened.data.steps[0].id)
    assert [st.status for st in ran] == ["done"] * 5
    assert [st.outputs for st in reopened.data.steps] == before
    assert all(aid in reopened.artifacts for outs in before for aid in outs)


def test_steps_saved_mid_turn_are_rejected_or_failed_and_a_replay_never_runs_an_unapproved_one(tmp_path):
    s = meme(tmp_path)
    work = s.data.steps[0].params["image"]
    waiting = s.propose("draw", {"image": work, "circle": [[10, 10, 5]]}, "agent:fake")  # never approved
    approved = s.propose("flare", {"image": work, "at": [100, 100]}, "agent:fake")
    approved.status = "approved"  # approved, then badshop closed before it ran
    running = s.propose("filter", {"image": work, "names": ["emboss"]}, "user")
    running.status = "running"  # say, a file written by a badshop that died mid-step
    reopened = project.open_project(project.save(s, tmp_path / "meme"), output_dir=tmp_path)
    assert [st.status for st in reopened.data.steps] == ["done"] * 5 + ["rejected", "error", "error"]
    back = reopened.step(waiting.id)
    assert back.error is None and back.outputs == [] and back.finished_at is not None
    assert back.result_text == "rejected: badshop closed before it was approved"
    for sid in (approved.id, running.id):
        back = reopened.step(sid)
        assert back.error.message == "badshop closed before this step finished"
        assert back.finished_at is not None
        assert back.result_text == f"error: {back.error.message}\nhint: {back.error.hint}"
    # a replay (auto_replay after an edit does one) runs what was approved and skips the unapproved draw
    ran = reopened.replay_from(reopened.data.steps[0].id)
    assert [st.id for st in ran] == [st.id for st in reopened.data.steps if st.id != waiting.id]
    assert [st.status for st in ran] == ["done"] * 7
    assert reopened.step(waiting.id).status == "rejected" and reopened.step(waiting.id).outputs == []


def test_save_replaces_the_old_file_in_one_step(tmp_path, monkeypatch):
    s = meme(tmp_path)
    path = project.save(s, tmp_path / "meme.badshop")
    assert project.save(s, path) == path  # overwrite: the extension isn't doubled
    old = path.read_bytes()
    s.run_tool("filter", {"image": s.data.steps[0].outputs[0], "names": ["emboss"]}, "user")

    def disk_full(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(project.os, "replace", disk_full)
    with pytest.raises(EngineError, match="can't save .*No space left") as e:
        project.save(s, path)
    assert "writable" in e.value.hint
    assert path.read_bytes() == old  # the previous save is whole
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".part")] == []  # no temp file left


def test_a_saved_project_gets_the_mode_any_saved_file_gets(saved, tmp_path):
    s, _ = saved
    old = os.umask(0o022)
    try:
        path = project.save(s, tmp_path / "shared")
    finally:
        os.umask(old)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644  # the umask decides, not a temp file's 0600
    path.chmod(0o600)  # made private by its owner: saving over it keeps that
    project.save(s, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_lone_surrogate_saves_and_reads_back(tmp_path):
    # A JSON client can send a lone surrogate (half an emoji) in any text, and pydantic keeps it.
    s = Session.new("half", output_dir=tmp_path)
    s.add_message("user", [Part(type="text", text="half an emoji: \ud83d")])
    project.save(s, tmp_path / "half")
    project.save(s, tmp_path / "half")  # the next autosave works too
    reopened = project.open_project(tmp_path / "half.badshop", output_dir=tmp_path)
    assert reopened.data.messages[0].content[0].text == "half an emoji: \ud83d"


@pytest.mark.parametrize("limit", ["MAX_SESSION_BYTES", "MAX_MEMBER_BYTES", "MAX_PROJECT_BYTES"])
def test_save_refuses_a_project_too_big_to_open_again(saved, tmp_path, monkeypatch, limit):
    s, _ = saved
    monkeypatch.setattr(project, limit, 5000)
    with pytest.raises(EngineError, match="too big to open again") as e:
        project.save(s, tmp_path / "big")
    assert "export" in e.value.hint
    assert list(tmp_path.iterdir()) == []  # nothing written, not even a temp file


# --- opening what badshop didn't write (review focus 3) ---


@pytest.fixture(scope="module")
def saved(tmp_path_factory) -> tuple[Session, Path]:
    tmp = tmp_path_factory.mktemp("saved")
    s = meme(tmp)
    return s, project.save(s, tmp / "good")


def rewrite(good: Path, dst: Path, edit) -> Path:
    """A copy of the project with its members edited. edit(members, payload) changes them in place;
    session.json is then written from payload, unless edit set it (to bytes, or to None to leave it out)."""
    with zipfile.ZipFile(good) as zf:
        members = {name: zf.read(name) for name in zf.namelist()}
    payload = json.loads(members.pop("session.json"))
    edit(members, payload)
    members.setdefault("session.json", json.dumps(payload).encode())
    with zipfile.ZipFile(dst, "w") as zf:
        for name, data in members.items():
            if data is not None:
                zf.writestr(name, data)
    return dst


def edited(edit):
    return lambda good, dst: rewrite(good, dst, edit)


def first_input(payload: dict) -> tuple[str, str]:
    """The first step's input (lincoln's working copy): its id and member name."""
    aid = payload["steps"][0]["params"]["image"]
    return aid, f"artifacts/{aid}.png"


def not_a_zip(good: Path, dst: Path) -> Path:
    dst.write_bytes(b"this is not a zip file")
    return dst


def truncated(good: Path, dst: Path) -> Path:
    dst.write_bytes(good.read_bytes()[:good.stat().st_size // 2])
    return dst


def flip_a_stored_byte(good: Path, dst: Path) -> Path:
    """Flip one byte inside an artifact's stored data, so the zip's own CRC check fails."""
    data = bytearray(good.read_bytes())
    with zipfile.ZipFile(good) as zf:
        info = next(i for i in zf.infolist() if i.filename.startswith("artifacts/"))
    name_len = int.from_bytes(data[info.header_offset + 26:info.header_offset + 28], "little")
    extra_len = int.from_bytes(data[info.header_offset + 28:info.header_offset + 30], "little")
    data[info.header_offset + 30 + name_len + extra_len + 100] ^= 0xFF
    dst.write_bytes(bytes(data))
    return dst


def declared_size(name: str, size: int):
    """A copy whose headers say member `name` holds `size` bytes while its data inflates to more (a zip
    bomb's trick). zipfile trusts the central directory; the local header is changed to match."""
    def make(good: Path, dst: Path) -> Path:
        data = bytearray(good.read_bytes())
        at = struct.unpack_from("<I", data, data.rindex(b"PK\x05\x06") + 16)[0]  # the central directory
        while data[at:at + 4] == b"PK\x01\x02":
            n, m, k = struct.unpack_from("<HHH", data, at + 28)
            if data[at + 46:at + 46 + n] == name.encode():
                struct.pack_into("<I", data, at + 24, size)
                struct.pack_into("<I", data, struct.unpack_from("<I", data, at + 42)[0] + 22, size)
            at += 46 + n + m + k
        dst.write_bytes(bytes(data))
        return dst
    return make


def recompressed(method: int):
    """A copy with every member compressed with `method`."""
    def make(good: Path, dst: Path) -> Path:
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(dst, "w", method) as out:
            for info in src.infolist():
                out.writestr(info.filename, src.read(info))
        return dst
    return make


def a_folder(good: Path, dst: Path) -> Path:
    dst.mkdir()
    return dst


def swap_bytes(members: dict, payload: dict) -> None:
    members[first_input(payload)[1]] = png_bytes((8, 8), "red")


def drop_member(members: dict, payload: dict) -> None:
    del members[first_input(payload)[1]]


def unlist(members: dict, payload: dict) -> None:
    aid, name = first_input(payload)
    del members[name], payload["artifacts"][aid]


def garbage_artifact(members: dict, payload: dict) -> None:
    blob = b"not an image at all"
    aid = hashlib.sha256(blob).hexdigest()
    members[f"artifacts/{aid}.png"] = blob
    payload["artifacts"][aid] = dict(payload["artifacts"][first_input(payload)[0]], id=aid)


BAD = {  # case -> (make the file from the good one, what the error says)
    "not a zip": (not_a_zip, "isn't a badshop project"),
    "truncated": (truncated, "isn't a badshop project"),
    "corrupt member": (flip_a_stored_byte, "isn't a badshop project, or it is damaged"),
    "declared size lies": (declared_size("session.json", 10), "isn't a badshop project, or it is damaged"),
    "bzip2 members": (recompressed(zipfile.ZIP_BZIP2), "compressed in a way badshop never writes"),
    "lzma members": (recompressed(zipfile.ZIP_LZMA), "compressed in a way badshop never writes"),
    "no session.json": (edited(lambda m, p: m.update({"session.json": None})), "no session.json"),
    "session.json isn't json": (edited(lambda m, p: m.update({"session.json": b"{not json"})), "isn't JSON"),
    "newer schema": (edited(lambda m, p: p.update(schema=3)), "newer badshop"),
    "no schema": (edited(lambda m, p: p.pop("schema")), "no schema number"),
    "not a session": (edited(lambda m, p: p.update(steps="lots")), "isn't a badshop session"),
    "unknown tool": (edited(lambda m, p: p["steps"][0].update(tool="nope")), "doesn't have"),
    "bad step params": (edited(lambda m, p: p["steps"][0]["params"].update(image={"x": 1})), "bad parameters"),
    "member climbing out": (edited(lambda m, p: m.update({"../../x": b"owned"})), "isn't a safe badshop project"),
    "absolute member": (edited(lambda m, p: m.update({"/tmp/x": b"owned"})), "isn't a safe badshop project"),
    "windows member": (edited(lambda m, p: m.update({"..\\..\\x": b"owned"})), "isn't a safe badshop project"),
    "bytes don't match the id": (edited(swap_bytes), "doesn't match its id"),
    "missing artifact": (edited(drop_member), "is missing"),
    "referenced but unlisted": (edited(unlist), "is missing"),
    "not an image": (edited(garbage_artifact), "isn't an image"),
    "a folder": (a_folder, "can't open"),
    "no such file": (lambda good, dst: dst, "can't open"),
}


@pytest.mark.parametrize("case", BAD)
def test_a_bad_project_is_a_clean_error_and_changes_nothing(saved, tmp_path, case):
    s, good = saved
    make, message = BAD[case]
    before = snapshot(s)
    bad = make(good, tmp_path / "bad.badshop")
    with pytest.raises(EngineError, match=message) as e:
        project.open_project(bad, output_dir=tmp_path)
    assert e.value.hint
    assert snapshot(s) == before  # open_project never sees it (Task 12 tests CoreApp keeps its session)
    assert {p.name for p in tmp_path.iterdir()} <= {"bad.badshop"}  # nothing extracted, nothing written


def odd_id(where: str, odd: str):
    """An edit that puts `odd` in one of the places session.json holds a step or message id."""
    def edit(members: dict, payload: dict) -> None:
        if where == "step":
            payload["steps"][0]["id"] = odd
        elif where == "message":
            payload["messages"][0]["id"] = odd
        elif where == "message's step":
            payload["messages"][0]["step_ids"] = [odd]
        else:  # "artifact's step": the step that made it
            payload["artifacts"][payload["steps"][0]["outputs"][0]]["produced_by"] = odd
    return edit


ODD_IDS = {  # case -> (where in session.json, an id _next_id never makes: it writes s1, s2... m1, m2...)
    "superscript two": ("step", "s²"),  # isdigit() says yes, int() says no
    "5000 digits": ("step", "s" + "1" * 5000),  # past int()'s 4300-digit limit
    "ten digits": ("step", "s1000000000"),
    "leading zero": ("step", "s01"),
    "trailing new line": ("step", "s1\n"),  # a "$" in the pattern would let it through
    "message, superscript two": ("message", "m²"),
    "message, Arabic-Indic three": ("message", "m٣"),  # int() reads it; _next_id writes ASCII digits
    "message's step, 5000 digits": ("message's step", "s" + "9" * 5000),
    "artifact's step, superscript two": ("artifact's step", "s²"),
}


@pytest.mark.parametrize("case", ODD_IDS)
def test_an_id_badshop_never_makes_is_refused(saved, tmp_path, case):
    # Session._next_id reads every step and message id in the session. A hand-edited one like "s²" used to
    # open fine, then make every propose() and add_message() raise a bare ValueError.
    where, odd = ODD_IDS[case]
    s, good = saved
    before = snapshot(s)
    bad = rewrite(good, tmp_path / "bad.badshop", odd_id(where, odd))
    with pytest.raises(EngineError, match="an id badshop never makes") as e:
        project.open_project(bad, output_dir=tmp_path)
    assert e.value.hint
    assert snapshot(s) == before
    assert {p.name for p in tmp_path.iterdir()} == {"bad.badshop"}


def test_the_ids_badshop_makes_open_and_the_next_ones_follow(saved, tmp_path):
    s, good = saved

    def renumber(members: dict, payload: dict) -> None:  # nine digits, the most an id may have
        payload["steps"][4]["id"] = "s123456789"
        payload["messages"][0]["id"] = "m987654321"

    reopened = project.open_project(rewrite(good, tmp_path / "big.badshop", renumber), output_dir=tmp_path)
    work = reopened.data.steps[0].params["image"]
    assert reopened.propose("filter", {"image": work, "names": ["invert"]}, "user").id == "s123456790"
    assert reopened.add_message("user", [Part(type="text", text="more")]).id == "m987654322"


@pytest.mark.parametrize("limit", ["MAX_SESSION_BYTES", "MAX_MEMBER_BYTES", "MAX_PROJECT_BYTES"])
def test_a_project_too_big_to_read_is_refused(saved, tmp_path, monkeypatch, limit):
    s, good = saved
    monkeypatch.setattr(project, limit, 5000)
    with pytest.raises(EngineError, match="too big to open") as e:
        project.open_project(good, output_dir=tmp_path)
    assert "something else" in e.value.hint


def test_a_zip_bomb_is_refused_without_inflating_it(tmp_path):
    bomb = tmp_path / "bomb.badshop"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf, zf.open("session.json", "w") as fh:
        for _ in range(32):
            fh.write(b" " * 2**20)  # 32 MiB of spaces, about 32 KB deflated
    declared_size("session.json", 10)(bomb, bomb)  # and its headers say 10 bytes
    tracemalloc.start()
    try:
        with pytest.raises(EngineError, match="damaged"):  # zipfile stops at 10 bytes: a bad CRC
            project.open_project(bomb, output_dir=tmp_path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 8 * 2**20  # read a MiB at a time, never the 32 MiB it inflates to


def test_the_good_file_opens(saved, tmp_path):
    s, good = saved  # so each bad case above fails for its own reason
    assert [st.status for st in project.open_project(good, output_dir=tmp_path).data.steps] == ["done"] * 5


# --- autosave ---


def test_autosave_lands_in_the_data_dir_and_is_found_again(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    assert project.autosave_path() == tmp_path / "data" / "autosave" / "session.badshop"
    assert project.find_autosave() is None
    s = meme(tmp_path)
    project.autosave(s)
    assert project.find_autosave() == project.autosave_path()
    s.run_tool("filter", {"image": s.data.steps[0].outputs[0], "names": ["emboss"]}, "user")
    project.autosave(s)  # after every step: the same file, replaced
    assert [p.name for p in project.autosave_path().parent.iterdir()] == ["session.badshop"]
    restored = project.open_project(project.find_autosave(), output_dir=tmp_path)
    assert [st.tool for st in restored.data.steps] == ["filter", "cutout", "paste", "deepfry", "animate", "filter"]


def test_claim_autosave_sets_the_last_runs_autosave_aside_for_a_restore(tmp_path, monkeypatch):
    # spec §9: after a crash the next launch offers to restore the autosave, so the new session's first
    # change must not overwrite it (§10: a restarted core reopens it)
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    previous = tmp_path / "data" / "autosave" / "previous.badshop"
    assert project.claim_autosave() is None  # a first launch: nothing to offer
    assert not (tmp_path / "data").exists()  # and nothing made
    project.autosave(meme(tmp_path))  # the last run, which then crashed
    crashed = project.autosave_path().read_bytes()
    assert project.claim_autosave() == previous  # the next launch sets it aside
    assert project.find_autosave() is None and previous.read_bytes() == crashed
    assert project.claim_autosave() == previous  # a launch that changed nothing still offers it
    assert previous.read_bytes() == crashed
    fresh = Session.new("fresh", output_dir=tmp_path)
    fresh.add_message("user", [Part(type="text", text="something new")])
    project.autosave(fresh)  # this run's first change
    assert previous.read_bytes() == crashed  # the last run's autosave is still whole
    restored = project.open_project(previous, output_dir=tmp_path)
    assert [st.tool for st in restored.data.steps] == ["filter", "cutout", "paste", "deepfry", "animate"]
    assert project.claim_autosave() == previous  # the launch after this one offers this run's session
    assert project.find_autosave() is None
    assert project.open_project(previous, output_dir=tmp_path).data.name == "fresh"


def test_claim_autosave_never_raises_and_leaves_what_it_cant_move(tmp_path, monkeypatch):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    project.autosave(Session.new("kept", output_dir=tmp_path))

    def denied(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(project.os, "replace", denied)
    assert project.claim_autosave() is None  # nothing offered this time
    assert project.find_autosave() == project.autosave_path()  # the file waits for the next launch
