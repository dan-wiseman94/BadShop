# Plan 2: Sessions and local server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A headless badshop core: a session that stores every image as an immutable artifact and every tool call as a step, replays edited steps, saves and reopens project files, runs tools in a guarded worker process, drives an agent turn loop (scripted fake provider, approvals, step budget, stop), and serves all of it to the UI and MCP proxies over a local WebSocket JSON-RPC API.

**Architecture:** `session/` owns state: `ArtifactStore` (bytes by SHA-256), `Session` (steps, messages, replay, export) and `project` (`.badshop` zips, autosave). Tools never run in the core process's own code path: `Session` builds a `ToolCall` (validated params plus the input artifacts' bytes), and an `Executor` runs it: in-process for tests, or in a spawn-context worker process with a wall-clock limit, an RSS limit, cancel and restart. `agent/` holds the provider protocol, a scripted fake provider, the approval gate and the turn loop. `server/` wraps it all as JSON-RPC 2.0 methods and event notifications (`CoreApp`, testable without sockets) behind a token-checked WebSocket bound to 127.0.0.1, started by `badshop-core serve`. Every tool call, from the user, the agent or (in Plan 5) a CLI agent, goes through `Session`, the single choke point spec §5 requires.

**Tech Stack:** Python 3.12, uv, Pydantic v2, asyncio, `websockets` 15/16 (`websockets.asyncio`), `psutil`, multiprocessing (spawn), zipfile; everything from Plan 1 (Pillow, NumPy, OpenCV, rembg).

**Spec:** `docs/superpowers/specs/2026-09-26-badshop-app-design.md` (read §5.3, §5.4, §5.6, §6, §7, §9, §10, §11 before starting). Also read `docs/superpowers/plans/2026-09-27-plan-1-carry-forward.md` (what this plan must discharge) and the roadmap `docs/superpowers/plans/2026-09-26-roadmap.md`.

## Global Constraints

- Python `>=3.12,<3.14`, `uv`, run from `core/`. New runtime dependencies, exactly: `websockets>=15,<17` and `psutil>=6`. No new dev dependencies. The only other dependency change is raising rembg's floor to `rembg[cpu]>=2.0.85` (Task 4). Add nothing else.
- Every Plan 1 constraint still holds: the CLI keeps byte/stdout parity with `reference/badshop.py`; engine functions never print, exit or take paths; failures are `EngineError(message, hint)`, never tracebacks.
- Actors: `"user"` (the UI or CLI user), `"agent:<provider>"` (the in-app agent; this plan uses `"agent:fake"`), `"cli:<claude|codex|gemini>"` (Plan 5's MCP proxy). Only `"user"` is trusted: every other actor may reference only artifact ids of the current session, may not set user-only fields, and may not call session, file or settings methods.
- Artifact ids are the lowercase SHA-256 hex of the stored bytes. Artifacts are immutable. A ref is a full id or a unique prefix of at least 6 hex characters; stored step params always hold full ids.
- The server binds `127.0.0.1` only, on a random free port; its first stdout line is exactly `{"port": <int>, "token": "<token>"}`; a connection's first message must be `{"type": "hello", "token": <token>, "actor": <actor>}` or it is closed with code 1008.
- JSON-RPC 2.0 over WebSocket text frames; server events are JSON-RPC notifications.
- Project files: `.badshop` zip with `session.json` (`"schema": 1`), `artifacts/<sha256><ext>`, `recipe.json`. A newer schema is refused; keys and secrets never go in the file.
- Tool worker defaults: 120 s wall clock and 3072 MB RSS per tool call; any exception other than `EngineError`, a timeout, a memory kill or a crash is a failed step with a clean error, and the next call gets a fresh worker.
- Agent defaults: per-turn step budget 40; 3 consecutive invalid tool calls end the turn; approval modes `"auto"`, `"ask_changes"` (default; `read_only` tools run, everything else waits), `"ask_all"`.
- The test suite turns `ResourceWarning` and unraisable-exception warnings into errors: every test closes the files, sockets, pipes, processes and websockets it opens. There is no pytest-asyncio: async tests call `asyncio.run(...)`.
- Commit after every task with a conventional-commit message ending in the line `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push.

## Review Focus

1. **A client disconnects while a turn is running or a step waits for approval** (the user closes the app mid-turn). The turn is cancelled cleanly, pending approvals resolve as rejected, the core keeps serving, and a new client can connect and see the session. Pinned in Task 13.
2. **Two steps produce byte-identical outputs** (the same artifact id). The artifact keeps its first `produced_by`, and deleting or replaying one step never removes an artifact another step or a message still references. Pinned in Tasks 7 and 8.
3. **A corrupt, truncated, non-zip, newer-schema or hostile `.badshop`** (members like `../../x`, an artifact whose bytes don't match its id, a missing artifact). Opening it gives a clean `EngineError` and leaves the current session untouched. Pinned in Task 9.
4. **An edit to a middle step makes a later step fail** (an empty cutout box). Replay stops at the failing step, later steps stay `stale`, earlier outputs are intact, and a later good edit replays the rest. Pinned in Task 8.
5. **A tool that hangs, blows past the memory limit, raises a non-`EngineError`, or kills its own process.** The step fails with a clean error, and the very next tool call succeeds on a fresh worker. Pinned in Task 10.

---

## File map

```
core/pyproject.toml                                  + psutil (Task 10), + websockets (Task 12), script badshop-core (Task 13); rembg floor (Task 4)
core/src/badshop/
  engine/finish.py, text.py, common.py, compose.py   Plan 1 residuals                              (Task 1)
  tools/registry.py, runner.py, catalog.py; engine/sources.py (FetchParams.clipboard)
                                                     validate/execute split, writes_files, user-only fields (Task 2)
  engine/sources.py                                  provenance in EngineResult.data["sources"]    (Task 3)
  engine/assets.py, engine/manifest.py (new), engine/cutout.py
                                                     asset manifest, progress, rembg via cached()  (Task 4)
  files.py (new)                                     final_path, default_output_dir                (Task 5)
  session/__init__.py, models.py, artifacts.py       data model, artifact store, import            (Task 5)
  session/netpolicy.py, execution.py                 tool-call boundary, private-address policy    (Task 6)
  session/session.py                                 propose, run, reject, export                  (Task 7)
  session/session.py                                 edit, replay, delete                          (Task 8)
  cli/argparse_gen.py (to_argv), session/project.py  project files, recipe export, autosave        (Task 9)
  session/worker.py                                  worker process with limits                    (Task 10)
  agent/__init__.py, provider.py, fake.py, approval.py, context.py, loop.py
                                                     provider protocol, fake provider, approvals, turn loop (Task 11)
  server/__init__.py, settings.py, rpc.py, app.py    settings, JSON-RPC dispatcher, methods, events (Task 12)
  server/ws.py, main.py, __main__.py                 WebSocket transport, handshake, entry point   (Task 13)
core/tests/test_residuals.py, test_tools_api.py, test_provenance.py, test_manifest.py, test_artifacts.py,
  test_execution.py, test_session.py, test_replay.py, test_project.py, test_worker.py, test_agent.py,
  test_server_app.py, test_server_ws.py
README.md, docs/superpowers/plans/2026-09-26-roadmap.md, docs/superpowers/plans/2026-09-27-plan-1-carry-forward.md (Task 13)
```

---

### Task 1: Plan 1 residuals (image budget floor, GIF still length, offline font retry window)

Plan 1 parked three engine residuals (rulings 80-82 in `docs/superpowers/plans/2026-09-27-plan-1-rulings.md`).
Plan 2's long-lived core hits each of them harder than the one-shot CLI did, so they are fixed first:

- **Budget floor (ruling 82).** `common.MAX_WORK_PIXELS` (50 Mpx) refuses an auto-sized caption layer or a
  big fit-box paste on a photo over about 100 Mpx, which the reference could handle. The limit becomes
  `max(MAX_WORK_PIXELS, floor)`, and the floor is the pixel count of the image the work goes onto.
- **GIF still length (ruling 80).** Pillow's GIF writer merges consecutive frames that look the same into one
  frame and adds up their delays. A GIF stores a delay as a 16-bit count of hundredths of a second, and the
  writer stores `int(ms / 10)`, so a merged still of 655,360 ms or more makes `Output.encode()` raise
  `struct.error`, for example with `animate --effect zoom --hold 100 --delay 10000` or `--frames 66 --delay 10000`.
  `animate` now refuses those animations with an `EngineError`, comparing in the writer's hundredths.
  `--frames 65 --delay 10000` (one 650 s still) still works, and so does `--frames 78 --delay 8402`: its
  655,356 ms still is stored as 65535 hundredths (655.35 s), exactly as the reference writes it.
- **Offline font retry window (ruling 81).** The auto-size loop in `caption()` looks the font up at every size
  it tries. Offline, each lookup retried the font download, so one Impact caption could wait on the network up
  to 7 times (once per size it tried). After a failed download, lookups now skip that download for
  `DOWNLOAD_RETRY_S` (60 s). The answer stays non-definitive, so it is never cached. A successful download
  clears the failure.

No successful run's pixels or stdout change, so the golden and parity tests stay green.

**Files:**
- Modify: `core/src/badshop/engine/common.py` (`check_size` gains `floor`)
- Modify: `core/src/badshop/engine/compose.py` (`paste`'s `scaled()` passes the base's pixel count)
- Modify: `core/src/badshop/engine/text.py` (the retry window in `_find_font_file`, `render_text(..., budget)`, the `caption()` call)
- Modify: `core/src/badshop/engine/finish.py` (`GIF_MAX_STILL_MS`, `_same_picture`, `_longest_still`, the guard in `animate`)
- Modify: `core/tests/test_text.py` (two existing tests: the retry test turns the window off, and the `render_text` spy accepts keywords)
- Create: `core/tests/test_residuals.py`

**Interfaces:**
- Consumes (Plan 1 code, as it is on `main`):
  - `common.MAX_WORK_PIXELS = 50_000_000`, `common.check_size(w: int, h: int) -> None`, `common.font(size) -> FreeTypeFont`
  - `text.find_font_file(style: str, explicit: str | None = None) -> str | None`,
    `text._find_font_file(style: str, explicit: str | None, data_dir: str) -> tuple[str | None, bool]`,
    `text._font_cache`, `text.SYSTEM_FONT_DIRS`, `text.FONT_CANDIDATES`, `text.FONT_DOWNLOADS: dict[str, assets.Pinned]`,
    `text.render_text(lines, fnt, style, color) -> Image`, `text.caption(p: TextParams, image) -> EngineResult`
  - `assets.cached(name, url, progress=None, sha256=None, size=None) -> Path` (raises `EngineError` when
    offline), `assets.Pinned(url, sha256, size)`, `assets.data_dir() -> Path`
  - `finish.dithered(im, colors)`, `finish.animate(p: AnimateParams, images) -> EngineResult`,
    `result.Output(key, image, name_hint, fmt="PNG", quality=None, frames=None, duration=None).encode() -> bytes`
  - `tools.runner.run_tool(name: str, raw: dict, store) -> ToolRun`, `tests/memstore.MemoryStore`
- Produces:
  - `common.check_size(w: int, h: int, floor: int = 0) -> None`: the limit is `max(MAX_WORK_PIXELS, floor)`,
    and the hint states that limit in megapixels.
  - `compose.paste`: `scaled()` calls `check_size(w, h, floor=base.width * base.height)`. This covers the
    `at`/`width`, `fit_box` and `repeat` paths.
  - `text.render_text(lines, fnt, style, color, budget: int = 0) -> Image` calls `check_size(W, H, floor=budget)`.
    `caption()` passes `budget=im.width * im.height`.
  - `text.DOWNLOAD_RETRY_S: float = 60.0` and `text._download_failed_at: dict[tuple[str, str], float]`, keyed by
    `(font file name, data dir string)` and holding the `time.monotonic()` of the last failed download.
  - `finish.GIF_MAX_STILL_MS = 655_350`, `finish._same_picture(a: Image, b: Image) -> bool`,
    `finish._longest_still(frames: list[Image]) -> int`. `animate` raises
    `EngineError("<n> identical frames in a row at <delay>ms would show one picture for <s> s, and a GIF frame
    lasts at most 655.35 s", hint="lower delay, hold or frames")` when
    `_longest_still(frames) * p.delay // 10 > GIF_MAX_STILL_MS // 10`. The comparison is in the GIF writer's units
    (Pillow writes `int(ms / 10)` as a 16-bit number), so a still of up to 655,359 ms is accepted, as the
    reference accepts it, and one of 655,360 ms or more is refused.
    It computes the runs only when `len(frames) * p.delay > GIF_MAX_STILL_MS`, since no single still can exceed the limit otherwise.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_residuals.py`:
```python
"""Plan 1's parked residuals: the image budget floor, the GIF still limit, the offline font retry window."""

import io
import struct

import pytest
from PIL import Image

from badshop.engine import assets, common, finish, text
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.tools.runner import run_tool
from memstore import MemoryStore

# --- the work budget never refuses something as big as the user's own image ---


def test_check_size_floor_raises_the_limit_never_lowers_it(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 10_000)
    common.check_size(100, 100)
    with pytest.raises(EngineError, match="that would make a 101x100 image"):
        common.check_size(101, 100)
    common.check_size(200, 100, floor=20_000)
    with pytest.raises(EngineError, match="that would make a 201x100 image") as e:
        common.check_size(201, 100, floor=20_000)
    assert "limit" in e.value.hint
    with pytest.raises(EngineError, match="that would make a 101x100 image"):
        common.check_size(101, 100, floor=5)


def test_paste_may_make_a_piece_as_big_as_the_base(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 10_000)
    store = MemoryStore()
    base = store.add(Image.new("RGB", (200, 200), "white"), "base.png")  # 40,000 px, over the budget
    piece = store.add(Image.new("RGBA", (10, 10), "red"), "piece.png")
    run = run_tool("paste", {"base": base, "piece": piece, "fit_box": [0, 0, 150, 150]}, store)
    assert run.result.lines[-1].endswith("150x150 after scaling")  # over the budget, under the base
    run = run_tool("paste", {"base": base, "piece": piece, "at": [0, 0], "width": 180}, store)
    assert run.result.lines[-1].endswith("180x180 after scaling")
    run_tool("paste", {"base": base, "piece": piece, "repeat": 3, "width": 120}, store)  # up to 180x180
    with pytest.raises(EngineError, match="that would make a 250x250 image"):
        run_tool("paste", {"base": base, "piece": piece, "fit_box": [0, 0, 250, 250]}, store)


def test_render_text_budget_is_the_floor(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 1_000)
    fnt = common.font(40)
    with pytest.raises(EngineError, match="that would make a"):
        text.render_text(["HELLO"], fnt, "impact", "red")
    layer = text.render_text(["HELLO"], fnt, "impact", "red", budget=60_000)
    assert 1_000 < layer.width * layer.height <= 60_000


def test_caption_may_be_as_big_as_its_image(monkeypatch):
    monkeypatch.setattr(common, "MAX_WORK_PIXELS", 1_000)
    monkeypatch.setattr(text, "find_font_file", lambda style, explicit=None: None)  # built-in font, offline
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (300, 200), "white"), "photo.png")  # 60,000 px
    run = run_tool("text", {"image": ref, "text": "hello", "size": 40}, store)
    assert run.result.lines[0].startswith("text: 1 line(s), impact style, font built-in, size 40px")
    with pytest.raises(EngineError, match="that would make a"):
        run_tool("text", {"image": ref, "text": "WWWW WWWW", "size": 200}, store)


# --- a GIF can't hold one picture for longer than 65535 hundredths of a second ---

def _still(colour: str) -> Image.Image:
    return Image.new("RGB", (24, 24), colour).quantize(colors=8)


def test_gif_writer_limit_is_the_one_animate_checks():
    # Pillow merges identical consecutive frames, adding their delays, into one 16-bit hundredths count.
    assert finish.GIF_MAX_STILL_MS == 65_535 * 10
    f = _still("red")
    fits = finish.GIF_MAX_STILL_MS // 10_000  # 65 frames of 10 s
    data = Output("a", f, "x", fmt="GIF", frames=[f] * fits, duration=10_000).encode()
    with Image.open(io.BytesIO(data)) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 650_000)
    with pytest.raises(struct.error):
        Output("a", f, "x", fmt="GIF", frames=[f] * (fits + 1), duration=10_000).encode()


def test_gif_writer_rounds_a_still_down_to_hundredths():
    # The writer stores int(ms / 10), so a still up to 655_359 ms fits (as 655.35 s) and 655_360 ms doesn't.
    f = _still("red")
    data = Output("a", f, "x", fmt="GIF", frames=[f] * 78, duration=8402).encode()  # 655_356 ms
    with Image.open(io.BytesIO(data)) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 655_350)
    with pytest.raises(struct.error):
        Output("a", f, "x", fmt="GIF", frames=[f] * 80, duration=8192).encode()  # 655_360 ms


def test_longest_still_counts_consecutive_identical_frames():
    red, blue = _still("red"), _still("blue")
    assert finish._longest_still([]) == 0
    assert finish._longest_still([red]) == 1
    assert finish._longest_still([red, red.copy(), blue, blue, blue, red]) == 3
    assert finish._longest_still([red, blue, red, blue]) == 1
    recoloured = red.copy()
    recoloured.putpalette([0, 0, 255] * 256)  # the same indices now mean blue: another picture
    assert finish._longest_still([red, recoloured]) == 1


def test_longest_still_merges_like_the_gif_writer_across_palettes():
    # Pillow compares frames whose palettes differ by their colors, so these 66 frames are one 660 s still.
    red = _still("red")
    unused_differ = red.copy()
    unused_differ.putpalette(red.getpalette()[:3] + [7] * 765)  # only unused entries change
    frames = [red] * 33 + [unused_differ] * 33
    assert finish._longest_still(frames) == 66
    with pytest.raises(struct.error):
        Output("a", red, "x", fmt="GIF", frames=frames, duration=10_000).encode()


def _animate(store: MemoryStore, ref: str, **params):
    return run_tool("animate", {"images": [ref], **params}, store)


def test_animate_holds_the_longest_still_a_gif_can_show():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    run = _animate(store, ref, frames=65, delay=10_000)
    with Image.open(io.BytesIO(run.result.outputs[0].encode())) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 650_000)


def test_animate_accepts_a_still_the_gif_writer_rounds_down(pair):
    # 78 x 8402 ms = 655_356 ms is past 655.35 s, but the writer stores it as 65535 hundredths: the reference
    # writes this GIF, so animate must write it too, frame for frame and duration for duration.
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    run = _animate(store, ref, frames=78, delay=8402)
    with Image.open(io.BytesIO(run.result.outputs[0].encode())) as im:
        assert (im.n_frames, im.info["duration"]) == (1, 655_350)
    pair.check("animate", "emoji_joy.png", "--frames", "78", "--delay", "8402", "--name", "a",
               files=["final/a.gif"])


@pytest.mark.parametrize("params", [
    {"frames": 66, "delay": 10_000},
    {"effect": "zoom", "frames": 2, "hold": 100, "delay": 10_000},  # Plan 1 ruling 80's struct.error
    {"frames": 80, "delay": 8192},  # 655_360 ms: the shortest still the writer can't store
], ids=["frames", "hold", "boundary"])
def test_animate_refuses_a_still_longer_than_a_gif_can_show(params):
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    with pytest.raises(EngineError, match="identical frames in a row") as e:
        _animate(store, ref, **params)
    assert e.value.hint == "lower delay, hold or frames"


def test_animate_long_moving_gifs_are_fine():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (24, 24), "red"), "red.png")
    run = _animate(store, ref, effect="flash", frames=120, delay=10_000)  # 20 minutes, never standing still
    with Image.open(io.BytesIO(run.result.outputs[0].encode())) as im:
        assert im.n_frames == 120


# --- offline, a caption tries the font download once, not on every auto-size step ---

@pytest.fixture
def offline_font(tmp_path, monkeypatch):
    """The impact style's only candidate is a font download that fails; returns the list of attempts."""
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])
    monkeypatch.setattr(text, "_font_cache", {})
    monkeypatch.setattr(text, "_download_failed_at", {})
    monkeypatch.setitem(text.FONT_CANDIDATES, "impact", ["BadshopTestDownload.ttf"])
    monkeypatch.setitem(text.FONT_DOWNLOADS, "BadshopTestDownload.ttf",
                        assets.Pinned("https://e.org/f.ttf", "0" * 64, 1))
    attempts = []

    def cached(name, url, **kw):
        attempts.append(name)
        raise EngineError(f"couldn't download {name} (offline)")
    monkeypatch.setattr(assets, "cached", cached)
    return attempts


@pytest.fixture
def lookups(monkeypatch):
    """Records every font lookup: caption's auto-size loop makes one per size it tries."""
    seen = []
    find = text.find_font_file
    monkeypatch.setattr(text, "find_font_file",
                        lambda style, explicit=None: seen.append(style) or find(style, explicit))
    return seen


def _long_caption() -> list[str]:
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (440, 300), "white"), "photo.png")
    return run_tool("text", {"image": ref, "text": "so many words in this caption " * 6}, store).result.lines


def test_offline_caption_tries_the_download_once(offline_font, lookups, monkeypatch):
    assert "font built-in" in _long_caption()[0]
    assert len(lookups) >= 3  # the caption shrank through several sizes
    assert offline_font == ["fonts/BadshopTestDownload.ttf"]
    _long_caption()
    assert len(offline_font) == 1  # the next caption is still inside the retry window

    monkeypatch.setattr(text, "DOWNLOAD_RETRY_S", 0.0)
    lookups.clear()
    _long_caption()
    assert len(offline_font) == 1 + len(lookups)  # no window: every lookup tries again


def test_font_download_is_retried_after_the_window(offline_font, tmp_path, monkeypatch):
    assert text.find_font_file("impact") is None
    assert text.find_font_file("impact") is None
    assert len(offline_font) == 1
    key = ("BadshopTestDownload.ttf", str(assets.data_dir()))
    assert key in text._download_failed_at
    text._download_failed_at[key] -= text.DOWNLOAD_RETRY_S  # the window has passed

    def cached(name, url, **kw):  # back online
        offline_font.append(name)
        (tmp_path / "fonts").mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(b"")
        return tmp_path / name
    monkeypatch.setattr(assets, "cached", cached)
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestDownload.ttf")
    assert len(offline_font) == 2
    assert key not in text._download_failed_at  # a success forgets the failure
    assert text.find_font_file("impact") == str(tmp_path / "fonts" / "BadshopTestDownload.ttf")
    assert len(offline_font) == 2  # and the answer is remembered
```

In `core/tests/test_text.py`, two existing tests depend on the old behaviour. Update both.

1. `test_font_lookup_retries_a_download_that_failed` checks that a lookup retries straight after a failed
   download. That is now the `DOWNLOAD_RETRY_S = 0` case, so turn the window off and give the test its own
   failure record. Replace:
```python
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])
    monkeypatch.setitem(text.FONT_CANDIDATES, "impact", ["BadshopTestDownload.ttf", "BadshopTestFallback.ttf"])
```
with:
```python
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])
    monkeypatch.setattr(text, "DOWNLOAD_RETRY_S", 0.0)  # no retry window: the next lookup tries again
    monkeypatch.setattr(text, "_download_failed_at", {})
    monkeypatch.setitem(text.FONT_CANDIDATES, "impact", ["BadshopTestDownload.ttf", "BadshopTestFallback.ttf"])
```

2. `test_line_breaks_in_every_style` spies on `render_text` with a lambda that takes positional arguments only.
   `caption()` now passes `budget=` as a keyword. Replace:
```python
    monkeypatch.setattr(text, "render_text", lambda lines, *a: seen.append(lines) or render(lines, *a))
```
with:
```python
    monkeypatch.setattr(text, "render_text",
                        lambda lines, *a, **kw: seen.append(lines) or render(lines, *a, **kw))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_residuals.py tests/test_text.py -q`
Expected: `11 failed, 26 passed, 2 errors`. The failures:
- `TypeError: check_size() got an unexpected keyword argument 'floor'`
- `TypeError: render_text() got an unexpected keyword argument 'budget'`
- `EngineError: that would make a 150x150 image, too big to work with` (paste) and `... a 137x57 image ...` (caption)
- `AttributeError: module 'badshop.engine.finish' has no attribute 'GIF_MAX_STILL_MS'` (and the same for `_longest_still`)
- `Failed: DID NOT RAISE EngineError` (the three `animate` refusal cases)
- `test_font_lookup_retries_a_download_that_failed`: `AttributeError: ... has no attribute 'DOWNLOAD_RETRY_S'`

The 2 errors are the `offline_font` fixture's `AttributeError: ... has no attribute '_download_failed_at'`.
The `test_line_breaks_in_every_style` cases pass both before and after the change. So do
`test_gif_writer_rounds_a_still_down_to_hundredths`, `test_animate_holds_the_longest_still_a_gif_can_show`,
`test_animate_accepts_a_still_the_gif_writer_rounds_down` and `test_animate_long_moving_gifs_are_fine`:
they pin the writer's rounding, the reference's output and the animations the new guard must not refuse.

- [ ] **Step 3: Implement the budget floor**

In `core/src/badshop/engine/common.py`, replace:
```python
def check_size(w: int, h: int) -> None:
    """Refuse, before Pillow tries to allocate it, an image that parameters blew up past the budget."""
    if w * h > MAX_WORK_PIXELS:
        raise EngineError(f"that would make a {w}x{h} image, too big to work with",
                          hint=f"use a smaller size or scale (the limit is {MAX_WORK_PIXELS // 1_000_000} megapixels)")
```
with:
```python
def check_size(w: int, h: int, floor: int = 0) -> None:
    """Refuse, before Pillow tries to allocate it, an image that parameters blew up past the budget.

    `floor` raises the limit to the pixels of an image the user already has (the photo a caption goes on,
    the base a piece is pasted onto): work as big as the user's own photo is never "too big"."""
    limit = max(MAX_WORK_PIXELS, floor)
    if w * h > limit:
        raise EngineError(f"that would make a {w}x{h} image, too big to work with",
                          hint=f"use a smaller size or scale (the limit is {limit // 1_000_000} megapixels)")
```

In `core/src/badshop/engine/compose.py` (inside `paste`), replace:
```python
    def scaled(width, height=None):
        w = max(1, round(width))
        h = max(1, round(height if height else piece.height * w / piece.width))
        check_size(w, h)
        return piece.resize((w, h), Image.NEAREST)
```
with:
```python
    def scaled(width, height=None):
        w = max(1, round(width))
        h = max(1, round(height if height else piece.height * w / piece.width))
        check_size(w, h, floor=base.width * base.height)  # a piece as big as the base is never too big
        return piece.resize((w, h), Image.NEAREST)
```

In `core/src/badshop/engine/text.py`, replace:
```python
def render_text(lines, fnt, style, color) -> Image.Image:
    """RGBA layer with the text, tight around it."""
```
with:
```python
def render_text(lines, fnt, style, color, budget: int = 0) -> Image.Image:
    """RGBA layer with the text, tight around it. `budget` is check_size's floor: the pixels of the image
    the text goes on, which the layer may use even past MAX_WORK_PIXELS."""
```
then, in the same function, replace:
```python
    H = lh * len(lines) + 2 * stroke + off + 4
    check_size(W, H)
```
with:
```python
    H = lh * len(lines) + 2 * stroke + off + 4
    check_size(W, H, floor=budget)
```
and in `caption()`, replace:
```python
    layer = render_text(lines, fnt, p.style, color)
```
with:
```python
    # a caption as big as the photo it goes on is never too big, even when the photo is over the budget
    layer = render_text(lines, fnt, p.style, color, budget=im.width * im.height)
```

(`cutout`'s sticker border keeps the plain `check_size(...)` call. The border pads the piece beyond its source,
so a floor equal to the source's pixels would not help it, and ruling 82 names only captions and pastes.)

- [ ] **Step 4: Implement the offline font retry window**

In `core/src/badshop/engine/text.py`, replace the imports:
```python
import glob
import re
from pathlib import Path
```
with:
```python
import glob
import re
import time
from pathlib import Path
```
Replace:
```python
_font_cache: dict[tuple[str, str | None, str], str | None] = {}
```
with:
```python
_font_cache: dict[tuple[str, str | None, str], str | None] = {}

# After a font download fails, lookups skip it for this long, so one offline caption (whose auto-size loop
# looks the font up at every size it tries) waits on the network once, not once per size.
DOWNLOAD_RETRY_S = 60.0
_download_failed_at: dict[tuple[str, str], float] = {}  # (font file name, data dir) -> time.monotonic()
```
and at the end of `_find_font_file`, replace:
```python
        if name in FONT_DOWNLOADS and not explicit:
            try:
                pin = FONT_DOWNLOADS[name]
                return str(assets.cached(f"fonts/{name}", pin.url, sha256=pin.sha256, size=pin.size)), definitive
            except EngineError:
                definitive = False  # offline: keep going down the list, and try the download again next time
    return None, definitive
```
with:
```python
        if name in FONT_DOWNLOADS and not explicit:
            key = (name, data_dir)
            failed_at = _download_failed_at.get(key)
            if failed_at is not None and time.monotonic() - failed_at < DOWNLOAD_RETRY_S:
                definitive = False  # it failed moments ago: fall back without waiting on the network again
                continue
            try:
                pin = FONT_DOWNLOADS[name]
                path = assets.cached(f"fonts/{name}", pin.url, sha256=pin.sha256, size=pin.size)
            except EngineError:
                _download_failed_at[key] = time.monotonic()
                definitive = False  # offline: keep going down the list, and try the download again later
                continue
            _download_failed_at.pop(key, None)
            return str(path), definitive
    return None, definitive
```
(The skip path keeps `definitive = False`, so `find_font_file` never caches the fallback. Once the window
passes, the next lookup tries the download again. An explicit `font` is never downloaded, as before.)

- [ ] **Step 5: Implement the GIF still limit**

In `core/src/badshop/engine/finish.py`, insert directly above `class AnimateParams(Params):`:
```python
# A GIF stores each frame's delay as a 16-bit count of hundredths of a second, and Pillow's writer merges
# identical consecutive frames into one, adding their delays: no single picture can show for longer. The
# writer stores int(ms / 10), so compare in hundredths (GIF_MAX_STILL_MS // 10): up to 655_359 ms still fits.
GIF_MAX_STILL_MS = 655_350


def _same_picture(a: Image.Image, b: Image.Image) -> bool:
    """Whether Pillow's GIF writer would merge frame b into frame a (GifImagePlugin._getbbox): the same
    palette indices under the same palette, or, when the palettes differ, the same colors pixel for pixel."""
    if a is b:
        return True
    if a.getpalette() == b.getpalette():
        return a.tobytes() == b.tobytes()
    return a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()


def _longest_still(frames: list[Image.Image]) -> int:
    """The most consecutive frames the GIF writer merges into one frame shown for their summed delay. Like
    the writer, each frame is compared with the first frame of the run it might join."""
    longest = run = 0
    first = None
    for f in frames:
        if first is not None and _same_picture(first, f):
            run += 1
        else:
            first, run = f, 1
        longest = max(longest, run)
    return longest


```
and in `animate`, replace:
```python
    if p.effect == "zoom" and p.hold:
        frames += [frames[-1]] * p.hold
    hint = f"final:{p.name}" if p.name else f"final:{{stem}}_{p.effect}"
```
with:
```python
    if p.effect == "zoom" and p.hold:
        frames += [frames[-1]] * p.hold
    if len(frames) * p.delay > GIF_MAX_STILL_MS:  # else no one picture can show for that long
        still = _longest_still(frames)
        # in the writer's units: it stores int(ms / 10) as a 16-bit number, or fails with a struct.error
        if still * p.delay // 10 > GIF_MAX_STILL_MS // 10:
            raise EngineError(f"{still} identical frames in a row at {p.delay}ms would show one picture for "
                              f"{still * p.delay / 1000:g} s, and a GIF frame lasts at most "
                              f"{GIF_MAX_STILL_MS / 1000:g} s", hint="lower delay, hold or frames")
    hint = f"final:{p.name}" if p.name else f"final:{{stem}}_{p.effect}"
```
(`finish.py` already imports `EngineError` and `Image`. Nothing else changes. The guard runs before the
`Output` is built, so the CLI, the in-process executor and the worker all get the same clean error instead of
a `struct.error` from `Output.encode()`. `_same_picture` follows Pillow 12's `_write_multiple_frames`/`_getbbox`, and
the `int(ms / 10)` comparison follows its `_write_local_header`. `test_gif_writer_limit_is_the_one_animate_checks`,
`test_gif_writer_rounds_a_still_down_to_hundredths` and `test_longest_still_merges_like_the_gif_writer_across_palettes`
pin that behaviour, so a Pillow upgrade that changes it fails loudly. The cheap `len(frames) * p.delay` pre-filter
stays in milliseconds: when the whole animation fits in 655,350 ms, so does every still.)

- [ ] **Step 6: Run the tests**

Run: `cd core && uv run pytest tests/test_residuals.py tests/test_text.py -q`
Expected: `39 passed`.

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `845 passed, 1 deselected` (Plan 1's 829 plus these 16; the deselected test is the `network` one),
and `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add core/src/badshop/engine/common.py core/src/badshop/engine/compose.py core/src/badshop/engine/text.py \
        core/src/badshop/engine/finish.py core/tests/test_residuals.py core/tests/test_text.py
git commit -m "fix(engine): Plan 1 residuals: image budget floor, GIF still limit, offline font retry window

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Tools API: validate/execute split, writes_files, user-only fields, llm_schema/ui_schema

This task discharges three carry-forward items: SP F15 (validation fused with execution), SEC-S8 (the
clipboard is user input) and the flag half of SEC-S7 (`export` writes a file although `mutates=False`). The
approval gate (Task 11), the execution boundary (Task 6), the session (Task 7) and `tools.list` (Task 12) build
on it. None of the five Review Focus items names this task. The tests below cover each carry-forward item.

**Files:**
- Modify: `core/src/badshop/engine/types.py` (the `USER_ONLY` marker), `core/src/badshop/engine/sources.py`
  (`FetchParams.clipboard`), `core/src/badshop/tools/registry.py`, `core/src/badshop/tools/runner.py`,
  `core/src/badshop/tools/catalog.py` (`export` flag, `fetch` description)
- Modify (test): `core/tests/test_catalog_parity.py` (the flag pin gains `writes_files`; the schema-validity test
  checks both schemas)
- Create: `core/tests/test_tools_api.py`

**Interfaces:**
- Consumes (Plan 1 code, as it is on `main`):
  - `badshop.tools.registry`: `ToolSpec(name, params, run, summary, description, category, mutates=True,
    network=False, read_only=False)`, `REGISTRY`, `get(name) -> ToolSpec` (EngineError `unknown tool 'x'`),
    `image_fields(params_cls) -> dict[str, bool]`, `llm_schema(spec)` (today just `spec.params.model_json_schema()`).
  - `badshop.tools.runner`: `ToolRun(tool, params, refs, result)`, `_explain(e)`, `_stem(params)`,
    `run_tool(name, raw, store)`; its only caller outside tests is `cli/main.py`: `run_tool(a._tool, raw, store)`.
  - `badshop.tools.context.Store`; `badshop.engine.types.Params` (`extra="forbid"`, so every schema has
    `"additionalProperties": false`); `badshop.engine.sources.FetchParams`, `sources.read_clipboard()` (called as a
    module global, so tests swap it).
  - Test helpers: `conftest.FIXTURES`, `memstore.MemoryStore`, `test_params.BASE` (the fewest valid params per tool).
- Produces:
  - `badshop.engine.types.USER_ONLY = "x-badshop-user-only"`, re-exported as `badshop.tools.registry.USER_ONLY`. A
    field is user-only when declared `Field(..., json_schema_extra={USER_ONLY: True})`.
  - `ToolSpec.writes_files: bool = False`. Only `export` sets it.
  - `registry.user_only_fields(params_cls: type[Params]) -> set[str]`: `{"clipboard"}` for `FetchParams`, and an
    empty set for every other tool.
  - `registry.ui_schema(spec: ToolSpec) -> dict`: `spec.params.model_json_schema()`, a fresh dict on each call.
    User-only properties carry `"x-badshop-user-only": true`.
  - `registry.llm_schema(spec: ToolSpec) -> dict`: `ui_schema` without the user-only fields in `properties` and
    `required`. `required` is dropped when it would be empty, and every other key is identical. It returns a fresh
    dict on each call. Tools without user-only fields get exactly `ui_schema`.
  - `runner.is_trusted(actor: str) -> bool`: `actor == "user"`.
  - `runner.explain(e: ValidationError) -> str`: renamed from `_explain`, same text.
  - `runner.validate(name: str, raw: dict, actor: str = "user") -> Params`. An unknown tool raises `get`'s
    EngineError. A pydantic failure raises `EngineError(f"bad parameters for {name}", hint=explain(e))`, and this
    check runs first. For any actor but `"user"`, the first user-only field (in declaration order) whose validated
    value differs from `FieldInfo.get_default(call_default_factory=True)` raises
    `EngineError(f"{name}: {field} can only be set by the user", hint=f"leave {field} out, or ask the user to
    do it in the app")`. An explicit default (`"clipboard": false`) is accepted from anyone, so a stored step's full
    `model_dump(mode="json")` validates again for every actor.
  - `runner.execute(name: str, params: Params, store: Store, stem: str | None = None) -> ToolRun`. It raises
    `TypeError(f"{name} takes {Expected.__name__}, not {type(params).__name__}")` for another tool's Params.
    `stem=None` means `_stem(params)`, as the CLI has always done; any string, `""` included, is used as given.
  - `runner.run_tool(name: str, raw: dict, store: Store, actor: str = "user") -> ToolRun` is
    `execute(name, validate(name, raw, actor), store)`. The CLI call is unchanged, and `fetch --clipboard` still
    works there.
  - The `fetch` description (what a model reads) no longer says `clipboard=true`. It now says to ask the user to
    paste the image into the chat. The CLI prints `summary`, which is unchanged.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_tools_api.py`:
```python
"""The tools API sessions build on (spec 5.2-5.4; carry-forward SP F15, SEC-S7, SEC-S8): validation apart
from execution, the one trusted actor, user-only fields and the two schemas, and the writes_files flag."""

import json

import jsonschema
import pytest
from PIL import Image
from pydantic import Field, ValidationError

from badshop.engine import sources
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import ImageRef, Params
from badshop.tools import REGISTRY, registry, runner
from badshop.tools.registry import USER_ONLY, ToolSpec, llm_schema, ui_schema, user_only_fields
from conftest import FIXTURES
from memstore import MemoryStore
from test_params import BASE

UNTRUSTED = ["agent:fake", "cli:claude", "cli:codex", "cli:gemini"]


def _names(refs: list[str]) -> list[str]:
    return [ref.rsplit("/", 1)[1] for ref in refs]  # MemoryStore refs are mem:N/<name>


# --- actors ---

def test_only_the_user_is_trusted():
    assert runner.is_trusted("user")
    for actor in [*UNTRUSTED, "", "User", "user ", "agent:user", "cli:user"]:
        assert not runner.is_trusted(actor), actor


# --- validate apart from execute (SP F15: the approval gate validates, lets the user edit, then runs) ---

def test_validate_returns_the_params_and_touches_no_store():
    params = runner.validate("prep", {"image": "never/loaded.png", "max": "500"})
    assert type(params) is REGISTRY["prep"].params
    assert params.image == "never/loaded.png" and params.max == 500


def test_validate_explains_bad_parameters():
    with pytest.raises(EngineError, match="^bad parameters for prep$") as e:
        runner.validate("prep", {"image": "a.png", "max": "big", "colour": 1})
    assert e.value.hint == ("max: Input should be a valid integer, unable to parse string as an integer; "
                            "colour: Extra inputs are not permitted")
    with pytest.raises(EngineError, match="^bad parameters for prep$") as e:
        runner.validate("prep", ["a.png"], "agent:fake")  # a model's arguments that are not an object
    assert e.value.hint == "params: Input should be a valid dictionary or instance of PrepParams"
    with pytest.raises(EngineError, match="unknown tool 'nope'"):
        runner.validate("nope", {})


def test_explain_is_public():
    with pytest.raises(ValidationError) as e:
        REGISTRY["prep"].params.model_validate({"max": 3})
    assert runner.explain(e.value) == ("image: Field required; "
                                       "max: Input should be greater than or equal to 16")


def test_execute_names_outputs_from_the_image_ref_by_default():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (40, 20), "white"), "lincoln.png")
    params = runner.validate("prep", {"image": ref})
    run = runner.execute("prep", params, store)
    assert run.tool == "prep" and run.params is params
    assert _names(run.refs) == ["lincoln_work.png", "lincoln_work_grid.png"]
    assert run.result.lines == ["size: 40x20"]


def test_execute_takes_an_explicit_stem():
    # A session's refs are artifact ids: it names outputs after the input's label instead.
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (40, 20), "white"), "a3f9c1d2e5b7.png")
    params = runner.validate("prep", {"image": ref})
    assert _names(runner.execute("prep", params, store, stem="lincoln").refs) == [
        "lincoln_work.png", "lincoln_work_grid.png"]
    assert _names(runner.execute("prep", params, store, stem="").refs) == ["_work.png", "_work_grid.png"]


def test_execute_refuses_another_tools_params():
    params = runner.validate("info", {"image": "mem:0/x.png"})
    with pytest.raises(TypeError, match="^prep takes PrepParams, not InfoParams$"):
        runner.execute("prep", params, MemoryStore())


@pytest.mark.parametrize("actor", ["user", *UNTRUSTED])
def test_every_tool_accepts_plain_params_from_every_actor(actor):
    # Only user-only fields are restricted, and a stored step's full dump (defaults included) validates
    # again for anyone, so a replay or an edit never trips over a default the model never set.
    for name, raw in BASE.items():
        params = runner.validate(name, raw, actor)
        assert runner.validate(name, params.model_dump(mode="json"), actor) == params


# --- user-only fields (SEC-S8: the clipboard is user input) ---

def test_the_clipboard_is_the_only_user_only_field():
    assert registry.USER_ONLY == "x-badshop-user-only"
    found = {name: user_only_fields(spec.params) for name, spec in REGISTRY.items()}
    assert {name: fields for name, fields in found.items() if fields} == {"fetch": {"clipboard"}}


@pytest.mark.parametrize("actor", UNTRUSTED)
@pytest.mark.parametrize("value", [True, 1, "true", "yes"])
def test_a_model_cannot_read_the_clipboard(monkeypatch, actor, value):
    # A steered model could pull a password-manager screenshot, or a one-click login link, off the clipboard.
    monkeypatch.setattr(sources, "read_clipboard", lambda: pytest.fail("a model read the clipboard"))
    with pytest.raises(EngineError, match="^fetch: clipboard can only be set by the user$") as e:
        runner.run_tool("fetch", {"clipboard": value}, MemoryStore(), actor=actor)
    assert e.value.hint == "leave clipboard out, or ask the user to do it in the app"
    with pytest.raises(EngineError, match="^fetch: clipboard can only be set by the user$"):
        runner.validate("fetch", {"query": "cat", "clipboard": value}, actor)


@pytest.mark.parametrize("actor", UNTRUSTED)
def test_a_model_may_leave_the_clipboard_at_its_default(actor):
    for raw in ({"query": "cat"}, {"query": "cat", "clipboard": False}, {"query": "cat", "clipboard": "no"}):
        assert runner.validate("fetch", raw, actor).clipboard is False


def test_the_user_still_reads_the_clipboard(monkeypatch):
    monkeypatch.setattr(sources, "read_clipboard", lambda: ((FIXTURES / "lincoln.png").read_bytes(), None))
    run = runner.run_tool("fetch", {"clipboard": True}, MemoryStore(), actor="user")
    assert [o.key for o in run.result.outputs] == ["fetched"]


class _Secret(Params):
    image: ImageRef
    note: list[str] = Field(default_factory=list, json_schema_extra={USER_ONLY: True})
    path: str | None = Field(None, description="a file the user picks", json_schema_extra={USER_ONLY: True})
    size: int = 3


class _RequiredSecret(Params):
    image: ImageRef
    path: str = Field(json_schema_extra={USER_ONLY: True})


class _OnlySecret(Params):
    path: str = Field(json_schema_extra={USER_ONLY: True})


def _spec(name: str, params: type[Params]) -> ToolSpec:
    return ToolSpec(name=name, params=params, category="inspect", summary="test tool",
                    description="a tool that only exists in this test file",
                    run=lambda p, s: EngineResult(lines=[f"{p.note} {p.path} {p.size}"]))


def test_user_only_fields_bind_every_untrusted_actor(monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "_secret", _spec("_secret", _Secret))
    assert user_only_fields(_Secret) == {"note", "path"}
    raw = {"image": "a.png", "note": ["hi"], "path": "/home/me/p.png"}
    assert runner.run_tool("_secret", raw, MemoryStore()).result.lines == ["['hi'] /home/me/p.png 3"]
    for actor in UNTRUSTED:
        with pytest.raises(EngineError, match="^_secret: note can only be set by the user$"):
            runner.validate("_secret", raw, actor)  # the first user-only field, in declaration order
        with pytest.raises(EngineError, match="^_secret: path can only be set by the user$"):
            runner.validate("_secret", {"image": "a.png", "path": "/home/me/p.png"}, actor)
        # Defaults, a default_factory's included, are fine; so is everything that isn't user-only.
        plain = {"image": "a.png", "note": [], "path": None, "size": 9}
        assert runner.validate("_secret", plain, actor).size == 9


# --- the two schemas ---

def test_the_model_never_sees_the_clipboard():
    spec = REGISTRY["fetch"]
    ui, llm = ui_schema(spec), llm_schema(spec)
    assert ui == spec.params.model_json_schema()
    assert ui["properties"]["clipboard"][USER_ONLY] is True  # the UI knows the field is the user's own
    assert list(llm["properties"]) == ["query", "source", "n"]
    assert llm["additionalProperties"] is False  # a model that sends clipboard anyway is off its schema
    jsonschema.Draft202012Validator.check_schema(llm)
    jsonschema.Draft202012Validator(llm).validate({"query": "cat", "n": 2})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(llm).validate({"query": "cat", "clipboard": True})


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_llm_schema_is_the_ui_schema_minus_user_only_fields(name):
    spec = REGISTRY[name]
    ui, llm, hidden = ui_schema(spec), llm_schema(spec), user_only_fields(spec.params)
    assert USER_ONLY not in json.dumps(llm)
    assert llm["properties"] == {k: v for k, v in ui["properties"].items() if k not in hidden}
    assert llm.get("required", []) == [k for k in ui.get("required", []) if k not in hidden]
    assert {k: v for k, v in llm.items() if k not in ("properties", "required")} == {
        k: v for k, v in ui.items() if k not in ("properties", "required")}


def test_llm_schema_drops_user_only_fields_from_required():
    llm = llm_schema(_spec("_required", _RequiredSecret))
    assert ui_schema(_spec("_required", _RequiredSecret))["required"] == ["image", "path"]
    assert llm["required"] == ["image"] and list(llm["properties"]) == ["image"]
    only = llm_schema(_spec("_only", _OnlySecret))
    assert only["properties"] == {} and "required" not in only  # an empty `required` is left out
    for schema in (llm, only):
        jsonschema.Draft202012Validator.check_schema(schema)


def test_schemas_are_fresh_copies():
    # Callers decorate what they get (tool definitions, forms); that must never leak into the next call.
    spec = REGISTRY["fetch"]
    llm_schema(spec)["properties"]["query"]["description"] = "changed"
    ui_schema(spec)["properties"].clear()
    assert llm_schema(spec)["properties"]["query"]["description"].startswith("search words")
    assert "clipboard" in ui_schema(spec)["properties"]


def test_descriptions_never_tell_a_model_to_set_a_user_only_field():
    for spec in REGISTRY.values():
        for field in user_only_fields(spec.params):
            assert f"{field}=" not in spec.description, (spec.name, field)
    assert "ask them to paste it into the chat" in REGISTRY["fetch"].description


# --- flags (SEC-S7: key the approval gate on read_only; export writes a file) ---

def test_writes_files_defaults_to_false_and_only_export_sets_it():
    assert _spec("_x", _OnlySecret).writes_files is False
    assert [name for name, spec in REGISTRY.items() if spec.writes_files] == ["export"]


def test_read_only_tools_change_nothing():
    # "Ask for changes" runs read_only tools without asking (spec 7): none may add images, use the
    # network or write a file.
    read_only = [spec for spec in REGISTRY.values() if spec.read_only]
    assert sorted(spec.name for spec in read_only) == ["find", "info", "view"]
    for spec in read_only:
        assert not (spec.mutates or spec.network or spec.writes_files), spec.name
```

In `core/tests/test_catalog_parity.py`, make three edits. First, replace the registry import line:
```python
from badshop.tools.registry import image_fields, llm_schema
```
with:
```python
from badshop.tools.registry import image_fields, llm_schema, ui_schema, user_only_fields
```

Second, replace `test_every_schema_is_valid_json_schema`. Today it validates the full dump, including
`clipboard`, against the model's schema, which now refuses that field:
```python
@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_schema_is_valid_json_schema(name):
    # Spec 11: the schema a model (or a UI form) receives must be a real JSON Schema, not merely one
    # pydantic can print. Pydantic writes draft 2020-12.
    schema = llm_schema(REGISTRY[name])
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(REGISTRY[name].params.model_validate(BASE[name]).model_dump(mode="json"))
```
with:
```python
@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_schema_is_valid_json_schema(name):
    # Spec 11: the schemas a UI form and a model receive must be real JSON Schemas, not merely ones
    # pydantic can print. Pydantic writes draft 2020-12. The model's schema has no user-only fields.
    spec = REGISTRY[name]
    dumped = spec.params.model_validate(BASE[name]).model_dump(mode="json")
    hidden = user_only_fields(spec.params)
    for schema, params in ((ui_schema(spec), dumped),
                           (llm_schema(spec), {k: v for k, v in dumped.items() if k not in hidden})):
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(params)
```

Third, replace the flag pin:
```python
# (mutates, network, read_only): the approval gate (spec 7) and the recipe log rely on these.
FLAGS = {
    **{n: (True, True, False) for n in ("fetch", "wiki", "emoji", "template")},
    **{n: (False, False, True) for n in ("info", "view", "find")},
    "export": (False, False, False),
    **{n: (True, False, False) for n in ("prep", "text", "cutout", "paste", "draw", "censor", "eyes", "filter",
                                         "warp", "flare", "sparkle", "watermark", "save", "deepfry", "animate")},
}


def test_tool_flags_are_pinned():
    assert {n: (s.mutates, s.network, s.read_only) for n, s in REGISTRY.items()} == FLAGS
```
with:
```python
# (mutates, network, read_only, writes_files): the approval gate (spec 7), the recipe log and the
# session's in-process export rely on these.
FLAGS = {
    **{n: (True, True, False, False) for n in ("fetch", "wiki", "emoji", "template")},
    **{n: (False, False, True, False) for n in ("info", "view", "find")},
    "export": (False, False, False, True),
    **{n: (True, False, False, False) for n in ("prep", "text", "cutout", "paste", "draw", "censor", "eyes",
                                                "filter", "warp", "flare", "sparkle", "watermark", "save",
                                                "deepfry", "animate")},
}


def test_tool_flags_are_pinned():
    assert {n: (s.mutates, s.network, s.read_only, s.writes_files) for n, s in REGISTRY.items()} == FLAGS
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_tools_api.py tests/test_catalog_parity.py -q`
Expected: 2 collection errors:
`ImportError: cannot import name 'USER_ONLY' from 'badshop.tools.registry'` (test_tools_api.py) and
`ImportError: cannot import name 'ui_schema' from 'badshop.tools.registry'` (test_catalog_parity.py).

- [ ] **Step 3: Add the user-only marker and mark the clipboard**

`USER_ONLY` lives in `engine/types.py`, beside the other schema markers. It cannot live in `tools/registry.py`:
`engine/sources.py` would then import `badshop.tools`, whose `__init__` imports `catalog`, which reads
`sources.FetchParams` while `sources` is still half-initialised
(`AttributeError: partially initialized module 'badshop.engine.sources' has no attribute 'FetchParams'`).

In `core/src/badshop/engine/types.py`, after this line:
```python
Seed = Annotated[int, Field(json_schema_extra={"format": "badshop-seed"})]  # same seed, same pixels: a reroll knob
```
insert:
```python

# Marks a field only the user may set (`Field(..., json_schema_extra={USER_ONLY: True})`), such as reading
# their clipboard: the schema a model sees leaves it out, and any other actor is refused unless it keeps
# the default. It lives here, beside the other schema markers, so engine modules can use it without
# importing badshop.tools (which imports them: a cycle). tools.registry re-exports it.
USER_ONLY = "x-badshop-user-only"
```

In `core/src/badshop/engine/sources.py`, replace the import:
```python
from badshop.engine.types import Params
```
with:
```python
from badshop.engine.types import USER_ONLY, Params
```
and in `class FetchParams`, replace:
```python
    clipboard: bool = Field(False, description="use the image (or image link) on the clipboard")
```
with:
```python
    # The clipboard is the user's input: a model could read a password-manager screenshot or a login link.
    clipboard: bool = Field(False, description="use the image (or image link) on the clipboard",
                            json_schema_extra={USER_ONLY: True})
```

- [ ] **Step 4: Registry: the flag, user-only fields, and the two schemas**

In `core/src/badshop/tools/registry.py`, replace the import:
```python
from badshop.engine.types import Params
```
with:
```python
from badshop.engine.types import USER_ONLY, Params
```

Replace the last lines of `ToolSpec`:
```python
    mutates: bool = True  # produces new images
    network: bool = False
    read_only: bool = False
```
with:
```python
    mutates: bool = True  # produces new images
    network: bool = False
    read_only: bool = False  # changes nothing: "ask for changes" runs it without asking (spec 7)
    writes_files: bool = False  # writes a file into the user's output folder (export)
```

Replace `llm_schema` at the end of the file:
```python
def llm_schema(spec: ToolSpec) -> dict:
    return spec.params.model_json_schema()
```
with:
```python
def user_only_fields(params_cls: type[Params]) -> set[str]:
    """Fields only the user may set: marked `json_schema_extra={USER_ONLY: True}`."""
    return {name for name, f in params_cls.model_fields.items()
            if isinstance(f.json_schema_extra, dict) and f.json_schema_extra.get(USER_ONLY) is True}


def ui_schema(spec: ToolSpec) -> dict:
    """The full parameter schema, for the UI's forms: user-only fields included and marked USER_ONLY."""
    return spec.params.model_json_schema()


def llm_schema(spec: ToolSpec) -> dict:
    """The schema a model sees (the in-app agent, CLI agents over MCP): user-only fields left out. The
    schema keeps `additionalProperties: false`, so a model that sends one anyway is off its schema, and
    runner.validate refuses it with a clean error."""
    schema = ui_schema(spec)
    hidden = user_only_fields(spec.params)
    if not hidden:
        return schema
    schema["properties"] = {k: v for k, v in schema["properties"].items() if k not in hidden}
    if "required" in schema:
        schema["required"] = [k for k in schema["required"] if k not in hidden]
        if not schema["required"]:  # leave the key out, as pydantic does for a model with no required field
            del schema["required"]
    return schema
```

- [ ] **Step 5: Runner: validate, execute, run_tool, is_trusted, explain**

In `core/src/badshop/tools/runner.py`, the current code from `_explain` to the end of the file is:
```python
def _explain(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'params'}: {err['msg']}" for err in e.errors())


def _stem(params: Params) -> str:
    for name, is_list in image_fields(type(params)).items():
        value = getattr(params, name)
        if is_list and value:
            value = value[0]
        if value:
            return PurePath(str(value)).stem
    return ""


def run_tool(name: str, raw: dict, store: Store) -> ToolRun:
    spec = get(name)
    try:
        params = spec.params.model_validate(raw)
    except ValidationError as e:
        raise EngineError(f"bad parameters for {name}", hint=_explain(e)) from None
    result = spec.run(params, store)
    stem = _stem(params)
    refs = [store.put(o, stem) for o in result.outputs]
    return ToolRun(name, params, refs, result)
```
Replace the whole file (`ToolRun` and `_stem` are unchanged) with:
```python
from dataclasses import dataclass
from pathlib import PurePath

from pydantic import ValidationError

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params
from badshop.tools.context import Store
from badshop.tools.registry import get, image_fields, user_only_fields


@dataclass
class ToolRun:
    tool: str
    params: Params
    refs: list[str]  # stored outputs, same order as result.outputs
    result: EngineResult


def is_trusted(actor: str) -> bool:
    """Only the user ("user": the UI or the CLI) is trusted; a model ("agent:<provider>") or a CLI agent
    ("cli:<name>") is not, whatever it claims."""
    return actor == "user"


def explain(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'params'}: {err['msg']}" for err in e.errors())


def _stem(params: Params) -> str:
    for name, is_list in image_fields(type(params)).items():
        value = getattr(params, name)
        if is_list and value:
            value = value[0]
        if value:
            return PurePath(str(value)).stem
    return ""


def validate(name: str, raw: dict, actor: str = "user") -> Params:
    """Check a call's parameters without running it (the approval gate shows them and lets the user edit
    them first). Any actor but the user must leave user-only fields at their defaults."""
    spec = get(name)
    try:
        params = spec.params.model_validate(raw)
    except ValidationError as e:
        raise EngineError(f"bad parameters for {name}", hint=explain(e)) from None
    if not is_trusted(actor):
        hidden = user_only_fields(spec.params)
        for field, info in spec.params.model_fields.items():  # declaration order: the first one is named
            if field in hidden and getattr(params, field) != info.get_default(call_default_factory=True):
                raise EngineError(f"{name}: {field} can only be set by the user",
                                  hint=f"leave {field} out, or ask the user to do it in the app")
    return params


def execute(name: str, params: Params, store: Store, stem: str | None = None) -> ToolRun:
    """Run validated parameters and put every output in the store, named from `stem` (`{stem}_work.png`).
    None takes the stem from the first image ref, as the CLI always has."""
    spec = get(name)
    if not isinstance(params, spec.params):
        raise TypeError(f"{name} takes {spec.params.__name__}, not {type(params).__name__}")
    result = spec.run(params, store)
    stem = _stem(params) if stem is None else stem
    refs = [store.put(o, stem) for o in result.outputs]
    return ToolRun(name, params, refs, result)


def run_tool(name: str, raw: dict, store: Store, actor: str = "user") -> ToolRun:
    """Validate, then run: the CLI's path, and any caller with no approval step in between."""
    return execute(name, validate(name, raw, actor), store)
```

`cli/main.py` needs no change: `run_tool(a._tool, raw, store)` runs as `"user"`. No module other than
`runner.py` imports `_explain`.

- [ ] **Step 6: Catalog: `export` writes files; `fetch` stops offering the clipboard to models**

In `core/src/badshop/tools/catalog.py`, in the `fetch` registration, replace:
```python
                 "angle. query may also be an image URL or a web page URL (its preview image is used). "
                 "clipboard=true takes what the user copied. For a named person or thing prefer wiki."),
```
with:
```python
                 "angle. query may also be an image URL or a web page URL (its preview image is used). "
                 "To use an image the user copied, ask them to paste it into the chat. For a named person "
                 "or thing prefer wiki."),
```
and in the `export` registration, replace:
```python
    name="export", params=basic.ExportParams, category="finish", mutates=False,
```
with:
```python
    name="export", params=basic.ExportParams, category="finish", mutates=False, writes_files=True,
```

- [ ] **Step 7: Run the tests**

Run: `cd core && uv run pytest tests/test_tools_api.py tests/test_catalog_parity.py -q`
Expected: `184 passed` (64 in test_tools_api.py, 120 in test_catalog_parity.py).

Then run the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `909 passed, 1 deselected` (Task 1's 845 plus these 64; test_catalog_parity.py's edits replace tests
without adding any, and the deselected test is the `network` one). The clipboard tests in test_sources.py still
pass, because `run_tool`'s actor defaults to `"user"`, just as the CLI's unchanged call runs as the user.
test_catalog_parity.py's `fetch --clipboard` span still validates, because it calls `model_validate` directly and
never checks an actor. Ruff prints `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add core/src/badshop/engine/types.py core/src/badshop/engine/sources.py core/src/badshop/tools/registry.py \
        core/src/badshop/tools/runner.py core/src/badshop/tools/catalog.py \
        core/tests/test_tools_api.py core/tests/test_catalog_parity.py
git commit -m "feat(tools): split validate from execute, add user-only fields, llm/ui schemas and writes_files

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Structured provenance for fetched images

**Files:**
- Modify: `core/src/badshop/engine/sources.py`
- Create: `core/tests/test_provenance.py`

**Interfaces:**
- Consumes (Plan 1 code, unchanged by Tasks 1-2 except where noted):
  - `badshop.engine.sources`: `fetch(p)`, `wiki(p)`, `emoji(p)`, `template(p)` (all wrapped in `_scrubbed`),
    `commons_search(query, n)`, `openverse_search(query, n)`, `download_candidates(hits, slug, source_line=None)`,
    `fetch_url(url, follow=True)`, `fetch_clipboard()`, `read_clipboard()`, `_clean(text)`, `TWEMOJI_URL`,
    `EMOJI_NAMES`, `http_get` (module global the tests swap).
  - `badshop.engine.result.EngineResult.data: dict` (Plan 1 leaves it `{}` for every source tool).
  - `badshop.tools.runner.run_tool(name, raw, store)` (Task 2 keeps this call shape: `actor` defaults to `"user"`,
    so `clipboard=True` stays allowed).
  - Test helpers: `tests/test_sources.py` `API`, `fake_http(requested, jpeg=None, duplicate=False)`,
    `first_commons_url()`; `tests/memstore.MemoryStore`; `tests/conftest.FIXTURES`.
  - Task 2 edits `FetchParams.clipboard` in the same file; none of the blocks below touch `FetchParams`.
- Produces (all in `badshop.engine.sources`):
  - The contract: every source tool's `EngineResult.data["sources"]` is a list aligned with `outputs` (same length and
    order). Each entry is `None` (the contact sheet) or a dict with exactly the keys of `SOURCE_KEYS`, each value a
    non-blank `str` or `None`. `template --list` (no outputs) returns `data == {"sources": []}`.
  - `SOURCE_KEYS = ("kind", "url", "page", "title", "license", "creator")`
  - `TWEMOJI_LICENSE = "CC-BY 4.0"`, `TWEMOJI_CREATOR = "Twitter/X and Twemoji contributors"`
  - `provenance(kind: str, url: str | None = None, *, page=None, title=None, license=None, creator=None) -> dict`
    (the only constructor of an entry; any non-string or blank value becomes `None`, strings are stripped)
  - `html_text(value) -> str | None` (text of an HTML snippet on one line; Commons extmetadata values are HTML)
  - `openverse_license(code, version) -> str | None` (`("by-nc", "2.0")` → `"CC BY-NC 2.0"`, `("cc0", "1.0")` →
    `"CC0 1.0"`, `("pdm", "1.0")` → `"Public Domain Mark 1.0"`)
  - `wiki_page(lang: str, title) -> str | None` (`https://<lang>.wikipedia.org/wiki/<Title_with_underscores>`,
    percent-encoded the way MediaWiki links it: `;@$!*(),/~:` stay literal)
  - `download_candidates` hits may carry a `"source"` dict from `provenance()`; the output's entry is that dict with
    `url` set to the link that delivered the bytes (the fallback thumbnail when the original failed). A hit without
    `"source"` gets `provenance("url", title=hit["title"])`.
  - `commons_search` requests `iiprop=url|mime|size|extmetadata` and `iiextmetadatafilter=LicenseShortName|Artist`.
  - `_scrubbed` also replaces control characters in every string of `data["sources"]` and strips the result,
    so a value that was only control characters (a server can send `"\x1b\x07"`) becomes `None`, never blank.
  - `_clean` also replaces every lone surrogate (U+D800-U+DFFF) with U+FFFD. `json.loads` turns a `"\ud800"`
    escape into one, and UTF-8 can't encode it, so it would make the CLI's print and the server's
    `model_dump_json` raise `UnicodeEncodeError`. Lines, captions, error text and `data["sources"]` all pass
    through `_clean`.
  - What each kind holds (`url` is always the link that delivered the bytes):

    | kind | page | title | license | creator |
    |---|---|---|---|---|
    | `commons` | imageinfo `descriptionurl` | file title without `File:` | extmetadata `LicenseShortName` | extmetadata `Artist` as text |
    | `openverse` | `foreign_landing_url` | `title` | `openverse_license(license, license_version)` | `creator` |
    | `wikipedia` | `wiki_page(lang, title)` | article title | None | None |
    | `imgflip` | None | template name | None | None |
    | `twemoji` | None | the emoji as captioned (`😂`) | `"CC-BY 4.0"` | `"Twitter/X and Twemoji contributors"` |
    | `url` | the web page when og:image was followed, else None | None | None | None |
    | `clipboard` | as `url` (a clipboard link) | None | None | None |

    A clipboard image has `url=None`; a clipboard link has `kind="clipboard"` and the `url`/`page` a plain `url`
    fetch of that link would have.

Nothing is parsed from captions, and the CLI's stdout and files do not change: captions, lines and output names are
untouched, the CLI never prints `data`, and the existing offline parity tests (`test_sources_match_the_reference_offline`)
keep passing unchanged.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_provenance.py`:
```python
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
```

The Commons extmetadata values above are real (the live API's replies for those files on 2026-09-27). The recorded
`tests/fixtures/api/commons.json` is not re-recorded: it has no `extmetadata`, which is exactly the "licence unknown"
path the first test pins.

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_provenance.py -q`
Expected: `29 failed`: the tool tests with `KeyError: 'sources'` (Plan 1's source tools return `data == {}`), the
helper tests with `AttributeError: module 'badshop.engine.sources' has no attribute 'html_text'` (and
`'openverse_license'`, `'wiki_page'`).

- [ ] **Step 3: Add the provenance helpers**

In `core/src/badshop/engine/sources.py`, make these four replacements.

(a) The module docstring. Replace:
```python
"""Image sources: Commons + Openverse search, Wikipedia lead images, Twemoji, Imgflip templates, the
clipboard, and plain image or page URLs. Ported from reference/badshop.py."""
```
with:
```python
"""Image sources: Commons + Openverse search, Wikipedia lead images, Twemoji, Imgflip templates, the
clipboard, and plain image or page URLs. Ported from reference/badshop.py.

Every tool here also returns `data["sources"]`: one provenance dict per output, in output order (None
for the contact sheet), with exactly the keys in SOURCE_KEYS. Sessions store it as the artifact's source
(spec §6); the CLI never prints it."""
```

(b) The imports. Replace:
```python
import urllib.parse
from html.parser import HTMLParser
```
with:
```python
import urllib.parse
from html import unescape
from html.parser import HTMLParser
```

(c) The constants. Replace:
```python
MAX_WEB_PIXELS = 64_000_000  # a fetched image bigger than this is refused before it is decoded
```
with:
```python
MAX_WEB_PIXELS = 64_000_000  # a fetched image bigger than this is refused before it is decoded
SOURCE_KEYS = ("kind", "url", "page", "title", "license", "creator")
TWEMOJI_LICENSE = "CC-BY 4.0"
TWEMOJI_CREATOR = "Twitter/X and Twemoji contributors"
```

(d) `_clean` and `_scrubbed`, followed by the new helpers. Replace `_clean` and the whole current `_scrubbed`:
```python
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _clean(text: str) -> str:
    """Control characters (terminal escapes, carriage returns, bells) become spaces."""
    return _CONTROL.sub(" ", text)


def _scrubbed(tool):
    """Web text (titles, creators, licences, page links, server messages) reaches the lines, captions
    and error text these tools return. Replace its control characters, so a server can't rewrite the
    user's terminal (an escape sequence plus a carriage return can erase a line and print a fake one)."""
    @functools.wraps(tool)
    def run(p):
        try:
            r = tool(p)
        except EngineError as e:
            e.message, e.hint = _clean(e.message), e.hint and _clean(e.hint)
            e.args = (e.message,)
            raise
        r.lines = [_clean(l) for l in r.lines]
        for o in r.outputs:
            o.caption = _clean(o.caption)
        return r
    return run
```
with:
```python
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _clean(text: str) -> str:
    """Control characters (terminal escapes, carriage returns, bells) become spaces, and lone surrogates
    become U+FFFD: json.loads makes one of a "\\ud800" escape, and UTF-8 (the CLI's stdout, the server's
    JSON) can't encode it."""
    return _SURROGATE.sub("�", _CONTROL.sub(" ", text))


def _scrubbed(tool):
    """Web text (titles, creators, licences, page links, server messages) reaches the lines, captions,
    provenance and error text these tools return. Replace its control characters, so a server can't
    rewrite the user's terminal (an escape sequence plus a carriage return can erase a line and print a
    fake one), nor the app's step details."""
    @functools.wraps(tool)
    def run(p):
        try:
            r = tool(p)
        except EngineError as e:
            e.message, e.hint = _clean(e.message), e.hint and _clean(e.hint)
            e.args = (e.message,)
            raise
        r.lines = [_clean(l) for l in r.lines]
        for o in r.outputs:
            o.caption = _clean(o.caption)
        if "sources" in r.data:  # stripped again: a value of only control characters is None, not blank
            r.data["sources"] = [s and {k: _text(_clean(v)) if isinstance(v, str) else v
                                        for k, v in s.items()} for s in r.data["sources"]]
        return r
    return run


def _text(value) -> str | None:
    """A remote value as provenance text: a non-blank string, stripped; anything else (a server may send
    numbers, lists or objects) is None."""
    return (value.strip() or None) if isinstance(value, str) else None


def provenance(kind: str, url: str | None = None, *,
               page=None, title=None, license=None, creator=None) -> dict:
    """One output's structured source (spec §6 Artifact.source): exactly SOURCE_KEYS, each value a
    non-blank string or None. `url` is the link that delivered the bytes, `page` the page to credit."""
    return {"kind": kind, "url": _text(url), "page": _text(page), "title": _text(title),
            "license": _text(license), "creator": _text(creator)}


_TAG = re.compile(r"<[^>]*>")


def html_text(value) -> str | None:
    """The text of an HTML snippet on one line (Commons' extmetadata values are HTML, e.g.
    `<a href="//commons.wikimedia.org/wiki/User:Barras">Barras</a>`); None if there is none."""
    if not isinstance(value, str):
        return None
    return " ".join(unescape(_TAG.sub(" ", value)).split()) or None


def _extmeta(info: dict, key: str):
    """One Commons extmetadata value, or None when the reply lacks it or has an odd shape."""
    meta = info.get("extmetadata")
    field = meta.get(key) if isinstance(meta, dict) else None
    return field.get("value") if isinstance(field, dict) else None


def openverse_license(code, version) -> str | None:
    """Openverse's licence code by its usual name: ("by-nc", "2.0") -> "CC BY-NC 2.0", ("cc0", "1.0") ->
    "CC0 1.0", ("pdm", "1.0") -> "Public Domain Mark 1.0"."""
    code = _text(code)
    if code is None:
        return None
    name = {"cc0": "CC0", "pdm": "Public Domain Mark"}.get(code.lower(), f"CC {code.upper()}")
    return f"{name} {_text(version) or ''}".strip()


def wiki_page(lang: str, title) -> str | None:
    """A Wikipedia article's address, spelled as MediaWiki links it: spaces become underscores, and
    everything but `;@$!*(),/~:` is percent-encoded."""
    title = _text(title)
    if title is None:
        return None
    return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"),
                                                                       safe=";@$!*(),/~:")
```

- [ ] **Step 4: Give search hits a source, and candidates their entries**

Still in `core/src/badshop/engine/sources.py`:

(a) `commons_search` asks for the licence and author. Replace:
```python
        "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 1200,
    }
    data, _ = http_get(COMMONS_API + "?" + urllib.parse.urlencode(params), max_bytes=MAX_TEXT)
    pages = json.loads(data).get("query", {}).get("pages", {})
    hits = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in IMAGE_MIMES:
            continue
        hits.append({
            "title": page.get("title", "").removeprefix("File:"),
            "url": info.get("thumburl") or info.get("url"),
            "note": "commons",
        })
    return hits[:n]
```
with:
```python
        "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 1200,
        "iiextmetadatafilter": "LicenseShortName|Artist",  # the licence and author, for provenance
    }
    data, _ = http_get(COMMONS_API + "?" + urllib.parse.urlencode(params), max_bytes=MAX_TEXT)
    pages = json.loads(data).get("query", {}).get("pages", {})
    hits = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in IMAGE_MIMES:
            continue
        title = page.get("title", "").removeprefix("File:")
        hits.append({
            "title": title,
            "url": info.get("thumburl") or info.get("url"),
            "note": "commons",
            "source": provenance("commons", page=info.get("descriptionurl"), title=title,
                                 license=html_text(_extmeta(info, "LicenseShortName")),
                                 creator=html_text(_extmeta(info, "Artist"))),
        })
    return hits[:n]
```

(b) `openverse_search`. Replace:
```python
        hits.append({
            "title": r.get("title") or "untitled",
            "url": r["url"], "fallback": r.get("thumbnail"),
            "note": f"openverse, {lic}, by {r.get('creator') or 'unknown'}",
        })
```
with:
```python
        hits.append({
            "title": r.get("title") or "untitled",
            "url": r["url"], "fallback": r.get("thumbnail"),
            "note": f"openverse, {lic}, by {r.get('creator') or 'unknown'}",
            "source": provenance("openverse", page=r.get("foreign_landing_url"), title=r.get("title"),
                                 license=openverse_license(r.get("license"), r.get("license_version")),
                                 creator=r.get("creator")),
        })
```

(c) The head of `download_candidates`. Replace:
```python
def download_candidates(hits, slug, source_line=None) -> EngineResult:
    """Download each hit as a numbered output, plus a contact sheet when there's a choice."""
    # reference/badshop.py download_candidates
    outputs, lines, panels = [], [], []
```
with:
```python
def download_candidates(hits, slug, source_line=None) -> EngineResult:
    """Download each hit as a numbered output, plus a contact sheet when there's a choice. A hit's
    "source" (from provenance(); a plain link when absent) becomes its output's data["sources"] entry,
    with the URL that delivered the bytes; the sheet's entry is None."""
    # reference/badshop.py download_candidates
    outputs, lines, panels, found = [], [], [], []
```

(d) The tail of `download_candidates` (after the download loop's `break`, `url` is the link that worked). Replace:
```python
        outputs.append(Output(str(i), kept, f"fetch/{slug}_{i}{EXT[fmt]}", fmt=fmt,
                              caption=f"({im.width}x{im.height}) {h['title']}{note}"))
    if not panels:
        raise EngineError("every candidate failed to download", hint=_hint(lines, "try other words or another source"))
    if len(panels) > 1:
        outputs.append(Output("sheet", contact_sheet(panels), f"fetch/{slug}_sheet.png"))
    if source_line:
        lines.append(source_line)
    return EngineResult(outputs=outputs, lines=lines)
```
with:
```python
        outputs.append(Output(str(i), kept, f"fetch/{slug}_{i}{EXT[fmt]}", fmt=fmt,
                              caption=f"({im.width}x{im.height}) {h['title']}{note}"))
        found.append({**(h.get("source") or provenance("url", title=h["title"])), "url": url})
    if not panels:
        raise EngineError("every candidate failed to download", hint=_hint(lines, "try other words or another source"))
    if len(panels) > 1:
        outputs.append(Output("sheet", contact_sheet(panels), f"fetch/{slug}_sheet.png"))
        found.append(None)
    if source_line:
        lines.append(source_line)
    return EngineResult(outputs=outputs, lines=lines, data={"sources": found})
```

- [ ] **Step 5: Links, the clipboard, Wikipedia, emoji and templates**

Still in `core/src/badshop/engine/sources.py`:

(a) `fetch_url`, the og:image branch. Replace:
```python
            if found:
                r = fetch_url(found, follow=False)
                r.lines.insert(0, f"page image: {found}")
                return r
```
with:
```python
            if found:
                r = fetch_url(found, follow=False)
                r.lines.insert(0, f"page image: {found}")
                r.data["sources"][0]["page"] = url
                return r
```

(b) `fetch_url`, its return. Replace:
```python
    name = "fetch/" + slugify(Path(urllib.parse.urlparse(url).path).stem) + ".png"
    return EngineResult(outputs=[Output("fetched", _keep(im), name)], lines=[f"size: {im.width}x{im.height}"])
```
with:
```python
    name = "fetch/" + slugify(Path(urllib.parse.urlparse(url).path).stem) + ".png"
    return EngineResult(outputs=[Output("fetched", _keep(im), name)], lines=[f"size: {im.width}x{im.height}"],
                        data={"sources": [provenance("url", url)]})
```

(c) `fetch_clipboard`. Replace:
```python
        out = Output("fetched", _keep(im), f"fetch/clipboard_{time.strftime('%H%M%S')}.png")
        return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}"])
    text = (text or "").strip()
    if re.match(r"https?://\S+$", text):
        r = fetch_url(text)
        r.lines.insert(0, f"clipboard holds a link: {text}")
        return r
```
with:
```python
        out = Output("fetched", _keep(im), f"fetch/clipboard_{time.strftime('%H%M%S')}.png")
        return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}"],
                            data={"sources": [provenance("clipboard")]})
    text = (text or "").strip()
    if re.match(r"https?://\S+$", text):
        r = fetch_url(text)
        r.lines.insert(0, f"clipboard holds a link: {text}")
        r.data["sources"][0]["kind"] = "clipboard"
        return r
```

(d) `wiki`, its hits. Replace:
```python
        hits = [{"title": q["title"], "url": q["thumbnail"]["source"], "note": "wikipedia lead image"}
                for q in pages if q.get("thumbnail")][:p.n]
```
with:
```python
        hits = [{"title": q["title"], "url": q["thumbnail"]["source"], "note": "wikipedia lead image",
                 "source": provenance("wikipedia", page=wiki_page(p.lang, q["title"]), title=q["title"])}
                for q in pages if q.get("thumbnail")][:p.n]
```

(e) `emoji`, its accumulators. Replace:
```python
    outputs, lines, missing = [], [], []
    for e in p.emoji:
```
with:
```python
    outputs, lines, missing, found = [], [], [], []
    for e in p.emoji:
```

(f) `emoji`, each output and the return (the caption text is unchanged). Replace:
```python
        outputs.append(Output("emoji", _keep(im), f"fetch/emoji_{code}.png",
                              caption=f"({im.width}x{im.height}) {EMOJI_NAMES.get(e.lower().strip(':'), e)}"))
    if not outputs:
        raise EngineError("no emoji downloaded", hint=_hint(missing, suggestion))
    lines.append("source: Twemoji (CC-BY 4.0), transparent PNGs; paste scales them with hard pixels")
    return EngineResult(outputs=outputs, lines=lines)
```
with:
```python
        shown = EMOJI_NAMES.get(e.lower().strip(':'), e)
        outputs.append(Output("emoji", _keep(im), f"fetch/emoji_{code}.png",
                              caption=f"({im.width}x{im.height}) {shown}"))
        found.append(provenance("twemoji", url, title=shown,
                                license=TWEMOJI_LICENSE, creator=TWEMOJI_CREATOR))
    if not outputs:
        raise EngineError("no emoji downloaded", hint=_hint(missing, suggestion))
    lines.append("source: Twemoji (CC-BY 4.0), transparent PNGs; paste scales them with hard pixels")
    return EngineResult(outputs=outputs, lines=lines, data={"sources": found})
```

(g) `template`, the listing (no outputs, so an empty list). Replace:
```python
        return EngineResult(lines=[f"{m['name']}  ({m['width']}x{m['height']}, {m['box_count']} text boxes)"
                                   for m in memes])
```
with:
```python
        return EngineResult(lines=[f"{m['name']}  ({m['width']}x{m['height']}, {m['box_count']} text boxes)"
                                   for m in memes], data={"sources": []})
```

(h) `template`, its hits. Replace:
```python
    hits = [{"title": m["name"], "url": m["url"], "note": f"{m['box_count']} text boxes"} for m in best]
```
with:
```python
    hits = [{"title": m["name"], "url": m["url"], "note": f"{m['box_count']} text boxes",
             "source": provenance("imgflip", title=m["name"])} for m in best]
```

- [ ] **Step 6: Run the tests**

Run: `cd core && uv run pytest tests/test_provenance.py tests/test_sources.py -q`
Expected: all PASS (`99 passed, 1 deselected`: this task's 29 plus `test_sources.py`'s 70; the deselected one is the
`network`-marked live test). `test_sources.py` passing unchanged, including every
`test_sources_match_the_reference_offline` case, is the proof that CLI stdout and files did not change.

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `938 passed, 1 deselected` (Task 2's 909 plus these 29), and `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add core/src/badshop/engine/sources.py core/tests/test_provenance.py
git commit -m "feat(sources): structured provenance for fetched images

Every source tool returns data[\"sources\"], aligned with its outputs (None for the
contact sheet): kind, url, page, title, license and creator, each a string or None.
Commons searches now request each file's licence and author (extmetadata), and url
is the link that delivered the bytes. Lone surrogates in remote text become U+FFFD,
so every line, caption and source encodes as UTF-8. CLI stdout and files are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

---

### Task 4: Asset manifest, download progress, rembg models through cached(), session cache

Discharges carry-forward SP F3 (a manifest of every download, a process-wide progress listener, rembg's weights
through `cached()` so pooch never runs or prints) and TRI T7 F3 (cache rembg sessions in the long-lived process and
drop them to save memory). No review-focus item names this task. CLI stdout and output files do not change:
`cutout` still gets the same u2net session, now built once per process.

**Files:**
- Create: `core/src/badshop/engine/manifest.py`, `core/tests/test_manifest.py`
- Modify: `core/src/badshop/engine/assets.py` (`PROGRESS`; `cached()` gains `md5` and `dest`),
  `core/src/badshop/engine/cutout.py` (`_SESSIONS`, `rembg_session`, `drop_sessions`),
  `core/tests/test_cutout_paste.py` (two superseded rembg-download tests move to `test_manifest.py`, rewritten),
  `core/pyproject.toml` (rembg's floor, `rembg[cpu]>=2.0.85`), `core/uv.lock` (through `uv lock`: only the
  `requires-dist` line for rembg changes; no package moves)

**Interfaces:**
- Consumes (Plan 1 code; Tasks 1-3 do not change these names):
  - `badshop.engine.assets`: `cached(name, url, progress=None, sha256=None, size=None) -> Path` (Plan 1 signature),
    `data_dir() -> Path`, `configure_rembg() -> None` (`setdefault`s `REMBG_HOME` to `data_dir()/rembg` and
    `U2NET_HOME` to `REMBG_HOME`), `CHUNK`, `OFFLINE_HINT`, `_not_pinned(name, why)`, `Pinned(url, sha256, size)`.
  - `badshop.engine.text`: `FONT_DOWNLOADS: dict[str, Pinned]` (keys `"Anton-Regular.ttf"`, `"ComicNeue-Bold.ttf"`),
    `SYSTEM_FONT_DIRS`, `find_font_file(style, explicit=None)`, which downloads with
    `assets.cached(f"fonts/{file}", pin.url, sha256=pin.sha256, size=pin.size)`. Task 1's retry window is keyed by
    (font file, data dir); the tests below use a fresh data dir, so the first attempt always happens.
  - `badshop.engine.faces`: `YUNET: Pinned`; `yunet_faces(cv2, bgr, min_score)`, whose first statement is
    `assets.cached("face_detection_yunet_2023mar.onnx", YUNET.url, sha256=YUNET.sha256, size=YUNET.size)`.
  - `badshop.engine.cutout`: `RembgModel = Literal["u2net", "u2net_human_seg", "isnet-anime", "birefnet-general"]`,
    `cutout(p, image)`.
  - rembg 2.0.85 (from `uv.lock`; Step 3 makes it the floor in `pyproject.toml`, because `asset_path` relies on
    `BaseSession.model_dir()` and the `models/<name>` layout): `rembg.sessions.sessions_class: list[type[BaseSession]]` and
    `rembg.sessions.sessions: dict[str, type[BaseSession]]`; `BaseSession.name()`; `BaseSession.model_dir()` =
    `<home>/models/<name>`, where `<home>` is `$U2NET_HOME` when set, else `$REMBG_HOME`; each class's
    `download_models()` returns an existing `<model_dir>/<name>.onnx` and only calls `pooch.retrieve` when that file is
    missing; `rembg.new_session(model)`; `rembg.remove(img, session=...)` (calls `session.predict(img)`).
  - Tests: `tests/memstore.MemoryStore`; `badshop.tools.runner.run_tool(name, raw, store)`.
- Produces:
  - `assets.PROGRESS: Callable[[str, int, int | None], None] | None = None`: called by `cached()` after every chunk
    of every download as `(name, done, total)`, on the downloading thread, in addition to the per-call `progress`. It
    must not raise (that aborts the download). Not called on a cache hit.
  - `assets.cached(name: str, url: str, progress=None, sha256: str | None = None, size: int | None = None,
    md5: str | None = None, dest: Path | None = None) -> Path`: `dest` is the absolute destination (default
    `data_dir() / name`); `md5` is checked like `sha256` ("it failed its checksum"); errors unchanged.
  - `badshop.engine.manifest`:
    - `@dataclass(frozen=True) class Asset: name: str; label: str; url: str; approx_mb: int; size: int | None = None;
      sha256: str | None = None; md5: str | None = None; rembg_model: str | None = None`
    - `ASSETS: tuple[Asset, ...]`, in this order: `fonts/Anton-Regular.ttf`, `fonts/ComicNeue-Bold.ttf`,
      `face_detection_yunet_2023mar.onnx`, `rembg/u2net.onnx`, `rembg/u2net_human_seg.onnx`,
      `rembg/isnet-anime.onnx`, `rembg/birefnet-general.onnx`. Each `name` is exactly the name passed to `cached()`,
      so `PROGRESS` events map to assets. Every asset has a pinned `size`, and either `sha256` (fonts, YuNet) or `md5`
      (rembg's own pins). `approx_mb = max(1, round(size / 2**20))`.
    - `get_asset(name: str) -> Asset` (`EngineError(f"unknown asset {name!r}", hint="assets: ...")`)
    - `asset_path(a: Asset) -> Path` (`data_dir() / name`; a rembg model: `<cls.model_dir()>/<model>.onnx`, with
      `cls` found in `rembg.sessions.sessions_class` by `cls.name()`, after `assets.configure_rembg()`)
    - `is_present(a: Asset) -> bool` (a file of the pinned size at `asset_path(a)`: exactly when `cached()` would not
      download)
    - `status() -> list[dict]` (one `{"name", "label", "approx_mb", "present"}` per asset, in `ASSETS` order)
    - `download(name: str) -> Path` (`cached()` with the asset's pins and `dest=asset_path(a)`)
    - `ensure_rembg_model(model: str) -> Path` (the same for the asset whose `rembg_model == model`; a model that is not
      in the manifest raises `EngineError(f"{model} is not a background remover badshop offers", hint="models: ...")`)
  - `badshop.engine.cutout`:
    - `_SESSIONS: dict[str, object]`: model to rembg session; it holds at most one entry (the last model used).
    - `rembg_session(model: str) -> object`: returns the cached session, or drops the cached one, calls
      `manifest.ensure_rembg_model(model)`, then `rembg.new_session(model)`, and caches the result.
    - `drop_sessions() -> None`
    - Errors: rembg missing (ImportError) gives `EngineError("rembg is not installed", hint='pip install "rembg[cpu]",
      or use no_ai')`, as before. A failed download re-raises `cached()`'s `EngineError` message (for example
      `couldn't download rembg/u2net.onnx (<urlopen error ...>)`) with `", or use no_ai"` appended to its hint. An
      `OSError`/`ValueError` from `new_session` keeps Plan 1's wording
      (`couldn't download the {model} background-removal model ({e})`).

Why the cache keeps only one session: in the prototype, building the u2net session raised RSS by about 370 MB, and its
first `remove()` added about 216 MB more. `drop_sessions()` gave back 290 to 430 MB (how much the allocator returns
varies from run to run). birefnet-general's weights are 5.5 times u2net's. Four cached models would pass the Task 10
worker's 3072 MB limit, and the cache would turn into memory-kill step failures. Switching models costs one rebuild
(0.3 to 0.6 s for u2net).

Why two Plan 1 tests are deleted: `test_cutout_model_download_offline` simulated "offline" by setting `HTTPS_PROXY`
to a dead port. That reached pooch's `requests`, but it never reaches `assets.cached()`. `assets._OPENER` is built at
import, and urllib's `ProxyHandler` reads the proxy variables when it is constructed. After this task that test would
really download 168 MB from GitHub, and a session cached by an earlier test would hide the failure anyway.
`test_cutout_corrupt_model_download` pinned pooch's md5 `ValueError`, which can no longer happen. It would also
download u2net in a non-`models` test on a fresh checkout. `test_manifest.py` replaces both with hermetic versions
(`test_cutout_model_download_offline`, `test_cutout_model_download_that_is_not_the_model`, and
`test_cutout_session_that_rembg_cannot_build` for the `new_session` error path).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_manifest.py`:
```python
"""The asset manifest, download progress, rembg's models through cached(), and the rembg session cache
(carry-forward SP F3 and TRI T7 F3)."""

import dataclasses
import hashlib
import inspect
import re
import sys
import tomllib
import typing
from importlib.metadata import version
from pathlib import Path

import pytest
from PIL import Image

from badshop.engine import assets, cutout, faces, manifest, text
from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from memstore import MemoryStore

REMBG_MD5 = {  # rembg 2.0.x's own pins, and exactly the models cutout offers (never bria-rmbg)
    "u2net": "60024c5c889badc19c04ad937298a77b",
    "u2net_human_seg": "c09ddc2e0104f800e3e1bb4652583d1f",
    "isnet-anime": "6f184e756bb3bd901c8849220a83e38e",
    "birefnet-general": "7a35a0141cbbc80de11d9c9a28f52697",
}


@pytest.fixture
def homes(monkeypatch, tmp_path):
    """Empty data and rembg dirs, and no rembg session cached by an earlier test."""
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    for k in ("REMBG_HOME", "U2NET_HOME"):
        monkeypatch.setenv(k, str(tmp_path / "rembg"))
    monkeypatch.setattr(cutout, "_SESSIONS", {})
    return tmp_path


def repoint(monkeypatch, name: str, **changes) -> manifest.Asset:
    """Swap one manifest entry for a copy with `changes` (tests point downloads at local files)."""
    new = dataclasses.replace(manifest.get_asset(name), **changes)
    monkeypatch.setattr(manifest, "ASSETS", tuple(new if a.name == name else a for a in manifest.ASSETS))
    return new


def pin_local(monkeypatch, tmp_path, name: str, body: bytes) -> manifest.Asset:
    """Serve `body` from a local file as the asset `name`, pinned (size and hash) to exactly those bytes."""
    src = tmp_path / "upstream" / name.replace("/", "_")
    src.parent.mkdir(exist_ok=True)
    src.write_bytes(body)
    old = manifest.get_asset(name)
    return repoint(monkeypatch, name, url=src.as_uri(), size=len(body),
                   sha256=hashlib.sha256(body).hexdigest() if old.sha256 else None,
                   md5=hashlib.md5(body).hexdigest() if old.md5 else None)


class FakeSession:
    """Stands in for a rembg session: its mask keeps the whole box."""

    def predict(self, img, *args, **kwargs):
        return [Image.new("L", img.size, 255)]


# --- cached(): the process-wide listener, md5, an explicit destination ---

def test_cached_reports_every_chunk_to_the_listener(homes, monkeypatch):
    src = homes / "src.bin"
    body = bytes(range(256)) * (3 * assets.CHUNK // 256 + 1)  # more than 3 chunks
    src.write_bytes(body)
    heard, own = [], []
    monkeypatch.setattr(assets, "PROGRESS", lambda *event: heard.append(event))
    path = assets.cached("sub/m.bin", src.as_uri(), progress=lambda done, total: own.append((done, total)))
    assert path.read_bytes() == body
    assert len(heard) >= 4 and {name for name, _, _ in heard} == {"sub/m.bin"}
    assert [(done, total) for _, done, total in heard] == own  # what the per-call callback heard too
    dones = [done for done, _ in own]
    assert dones == sorted(set(dones)) and own[-1] == (len(body), len(body))
    heard.clear()
    assets.cached("sub/m.bin", src.as_uri())  # a cache hit downloads nothing and reports nothing
    assert heard == []


def test_cached_checks_md5(homes):
    src = homes / "src.bin"
    src.write_bytes(b"model bytes")
    with pytest.raises(EngineError, match="failed its checksum") as e:
        assets.cached("m.onnx", src.as_uri(), md5="0" * 32)
    assert "upstream file changed" in e.value.hint
    assert list((homes / "data").iterdir()) == []  # nothing kept, not even the temp file
    good = hashlib.md5(b"model bytes").hexdigest()
    assert assets.cached("m.onnx", src.as_uri(), md5=good).read_bytes() == b"model bytes"


def test_cached_writes_to_an_explicit_destination(homes):
    src = homes / "src.bin"
    src.write_bytes(b"x" * 10)
    dest = homes / "elsewhere" / "deep" / "m.onnx"
    assert assets.cached("rembg/m.onnx", src.as_uri(), size=10, dest=dest) == dest
    assert dest.read_bytes() == b"x" * 10 and not (homes / "data").exists()
    assert [p.name for p in dest.parent.iterdir()] == ["m.onnx"]  # the temp file was renamed into place
    src.unlink()
    assert assets.cached("rembg/m.onnx", src.as_uri(), size=10, dest=dest) == dest  # a cache hit


# --- the manifest ---

def test_manifest_lists_every_download_once():
    names = [a.name for a in manifest.ASSETS]
    assert len(set(names)) == len(names)
    assert set(names) == ({f"fonts/{f}" for f in text.FONT_DOWNLOADS} | {"face_detection_yunet_2023mar.onnx"}
                          | {f"rembg/{m}.onnx" for m in REMBG_MD5})
    for a in manifest.ASSETS:
        assert a.label and a.size and a.approx_mb == max(1, round(a.size / 2**20)), a.name
        assert (a.sha256 is None) != (a.md5 is None), a.name  # exactly one pinned hash
    yunet = manifest.get_asset("face_detection_yunet_2023mar.onnx")
    assert (yunet.url, yunet.sha256, yunet.size) == faces.YUNET
    for file, pin in text.FONT_DOWNLOADS.items():
        font = manifest.get_asset(f"fonts/{file}")
        assert (font.url, font.sha256, font.size) == pin
    offered = {a.rembg_model: a.md5 for a in manifest.ASSETS if a.rembg_model}
    assert offered == REMBG_MD5 and set(offered) == set(typing.get_args(cutout.RembgModel))


def test_rembg_assets_are_rembgs_own_files():
    from rembg.sessions import sessions

    for a in manifest.ASSETS:
        if a.rembg_model:
            source = inspect.getsource(sessions[a.rembg_model].download_models)
            assert f'"{a.url}"' in source and f"md5:{a.md5}" in source, a.name


def test_rembg_floor_is_the_version_asset_path_was_checked_against():
    # asset_path relies on BaseSession.model_dir() and its <home>/models/<name> layout, checked against
    # rembg 2.0.85 (the locked version), so pyproject.toml accepts no older rembg.
    from rembg.sessions.base import BaseSession

    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    assert [d for d in deps if d.startswith("rembg")] == ["rembg[cpu]>=2.0.85"]
    installed = re.match(r"(\d+)\.(\d+)\.(\d+)", version("rembg"))
    assert installed and tuple(map(int, installed.groups())) >= (2, 0, 85)
    assert callable(BaseSession.model_dir)


def test_manifest_names_are_the_names_the_engine_downloads(homes, monkeypatch):
    asked = []

    def offline(name, url, **kw):
        asked.append((name, url, kw.get("sha256"), kw.get("size")))
        raise EngineError(f"couldn't download {name}")

    def not_installed(*args, **kwargs):
        raise OSError("no such font")

    monkeypatch.setattr(assets, "cached", offline)
    monkeypatch.setattr(text, "SYSTEM_FONT_DIRS", [])  # so only the downloadable lookalikes are left
    monkeypatch.setattr(text.ImageFont, "truetype", not_installed)
    assert text.find_font_file("impact") is None and text.find_font_file("paint") is None
    with pytest.raises(EngineError):
        faces.yunet_faces(None, None, 0.5)
    assert asked == [(a.name, a.url, a.sha256, a.size) for a in manifest.ASSETS if a.rembg_model is None]


def test_unknown_assets_and_models():
    with pytest.raises(EngineError, match="unknown asset 'nope'") as e:
        manifest.get_asset("nope")
    assert "rembg/u2net.onnx" in e.value.hint
    with pytest.raises(EngineError, match="bria-rmbg is not a background remover badshop offers") as e:
        manifest.ensure_rembg_model("bria-rmbg")
    assert "birefnet-general" in e.value.hint


def test_status_and_download(homes, monkeypatch):
    font = pin_local(monkeypatch, homes, "fonts/Anton-Regular.ttf", b"a font")
    rows = manifest.status()
    assert [r["name"] for r in rows] == [a.name for a in manifest.ASSETS]
    assert rows[0] == {"name": font.name, "label": font.label, "approx_mb": 1, "present": False}
    assert not any(r["present"] for r in rows)
    heard = []
    monkeypatch.setattr(assets, "PROGRESS", lambda *event: heard.append(event))
    path = manifest.download(font.name)
    assert path == homes / "data" / "fonts" / "Anton-Regular.ttf" and path.read_bytes() == b"a font"
    assert heard == [(font.name, 6, 6)]  # the event names the asset
    assert [r["name"] for r in manifest.status() if r["present"]] == [font.name]
    path.write_bytes(b"short")  # cut short by an older version: not present, and a download heals it
    assert not manifest.is_present(font)
    assert manifest.download(font.name).read_bytes() == b"a font"


@pytest.mark.parametrize("model", list(REMBG_MD5))
def test_rembg_models_land_where_rembg_looks(homes, monkeypatch, model):
    import pooch
    from rembg.sessions import sessions

    a = pin_local(monkeypatch, homes, f"rembg/{model}.onnx", f"{model} weights".encode())
    heard = []
    monkeypatch.setattr(assets, "PROGRESS", lambda *event: heard.append(event))
    path = manifest.ensure_rembg_model(model)
    assert path == homes / "rembg" / "models" / model / f"{model}.onnx" == manifest.asset_path(a)
    assert path.read_bytes() == f"{model} weights".encode() and manifest.is_present(a)
    assert [name for name, _, _ in heard] == [a.name]
    assert manifest.download(a.name) == path  # the same file whichever way it is asked for

    def no_pooch(*args, **kwargs):
        raise AssertionError("rembg downloaded the model itself")

    monkeypatch.setattr(pooch, "retrieve", no_pooch)
    assert sessions[model].download_models() == str(path)  # rembg finds our file and never calls pooch


# --- cutout: one session per model, download failures ---

def test_cutouts_reuse_one_session_per_model(homes, monkeypatch):
    import rembg

    pin_local(monkeypatch, homes, "rembg/u2net.onnx", b"u2net weights")
    pin_local(monkeypatch, homes, "rembg/isnet-anime.onnx", b"isnet-anime weights")
    built = []

    def new_session(model, *args, **kwargs):
        built.append(model)
        return FakeSession()

    monkeypatch.setattr(rembg, "new_session", new_session)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (40, 30), "red"), "x.png")
    for _ in range(2):
        run = run_tool("cutout", {"image": ref}, store)
        assert store.images[run.refs[0]].size == (40, 30)
    assert built == ["u2net"]
    first = cutout.rembg_session("u2net")
    cutout.rembg_session("isnet-anime")  # another model replaces it: one session in memory at a time
    assert list(cutout._SESSIONS) == ["isnet-anime"]
    assert cutout.rembg_session("u2net") is not first and built == ["u2net", "isnet-anime", "u2net"]
    cutout.drop_sessions()
    assert cutout._SESSIONS == {}


def test_cutout_model_download_offline(homes, monkeypatch):
    repoint(monkeypatch, "rembg/u2net.onnx", url=(homes / "nothing-here.onnx").as_uri())  # every GET fails
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match=r"couldn't download rembg/u2net.onnx \(") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "internet" in e.value.hint and e.value.hint.endswith("or use no_ai")
    assert list((homes / "rembg").rglob("*.onnx*")) == []
    assert cutout._SESSIONS == {}


def test_cutout_model_download_that_is_not_the_model(homes, monkeypatch):
    # A captive portal answers the model download with its login page: the pinned size catches it.
    portal = homes / "portal.html"
    portal.write_bytes(b"<html>log in to the cafe wifi</html>")
    repoint(monkeypatch, "rembg/u2net.onnx", url=portal.as_uri())
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match=r"rembg/u2net.onnx \(36 bytes, expected 175997641 bytes\)") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "upstream file changed" in e.value.hint and e.value.hint.endswith("or use no_ai")
    assert list((homes / "rembg").rglob("*.onnx*")) == []


def test_cutout_session_that_rembg_cannot_build(homes, monkeypatch):
    # The weights are in place, but rembg still fails (it re-downloads when the file vanished meanwhile).
    import rembg

    def gone(model, *args, **kwargs):
        raise OSError(f"{model}.onnx: No such file or directory")

    pin_local(monkeypatch, homes, "rembg/u2net.onnx", b"u2net weights")
    monkeypatch.setattr(rembg, "new_session", gone)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match=r"couldn't download the u2net background-removal model \(") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "internet" in e.value.hint and "no_ai" in e.value.hint
    assert cutout._SESSIONS == {}


def test_cutout_without_rembg(homes, monkeypatch):
    for module in ("rembg", "rembg.sessions"):
        monkeypatch.setitem(sys.modules, module, None)  # makes `import rembg` fail
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match="rembg is not installed") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "no_ai" in e.value.hint


@pytest.mark.models
def test_real_u2net_is_pinned_cached_and_quiet(monkeypatch, capfd):
    # A cache hit in core/.test-cache; a real, pinned download on a fresh checkout.
    monkeypatch.setattr(cutout, "_SESSIONS", {})
    a = manifest.get_asset("rembg/u2net.onnx")
    path = manifest.ensure_rembg_model("u2net")
    assert manifest.is_present(a)
    with path.open("rb") as fh:
        assert hashlib.file_digest(fh, "md5").hexdigest() == a.md5
    session = cutout.rembg_session("u2net")
    assert cutout.rembg_session("u2net") is session and type(session).__name__ == "U2netSession"
    out, err = capfd.readouterr()
    assert out == "" and "Downloading" not in err and "%|" not in err  # no pooch log line or tqdm bar
```

In `core/tests/test_cutout_paste.py`, delete these two tests (the whole block, including the two blank lines after
it; `test_manifest.py` above has their replacements):
```python
def test_cutout_model_download_offline(monkeypatch, tmp_path):
    for k in ("REMBG_HOME", "U2NET_HOME"):
        monkeypatch.setenv(k, str(tmp_path / "rembg"))
    for k in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")
    for k in ("NO_PROXY", "no_proxy"):  # so the dead proxy is always used and nothing is really downloaded
        monkeypatch.delenv(k, raising=False)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match="couldn't download the u2net background-removal model") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "internet" in e.value.hint


def test_cutout_corrupt_model_download(monkeypatch):
    # A captive portal answers the first model download with its login page: pooch's hash check fails.
    import rembg

    def portal(model):
        raise ValueError(f"MD5 hash of downloaded file ({model}.onnx) does not match the known hash")
    monkeypatch.setattr(rembg, "new_session", portal)
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError, match="couldn't download the u2net background-removal model") as e:
        run_tool("cutout", {"image": ref}, store)
    assert "internet" in e.value.hint and "does not match" in e.value.message


```
Every other import in that file stays in use (`ruff check` confirms it).

The test sizes and md5s are real. rembg's md5s come from rembg 2.0.85's session classes, and
`test_rembg_assets_are_rembgs_own_files` checks them against the installed rembg's source, and
`test_rembg_floor_is_the_version_asset_path_was_checked_against` pins the `rembg[cpu]>=2.0.85` floor Step 3 declares
(it reads `core/pyproject.toml` and the installed rembg's version). The sizes are GitHub's
`Content-Length` for each release file (checked on 2026-09-27); u2net's matches the file in `core/.test-cache`. Every
test except the `models`-marked one runs offline against local `file:` URLs in `tmp_path`. The `models` test is a
cache hit in `core/.test-cache/rembg`, or one real, pinned 168 MB download on a fresh checkout.

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_manifest.py -q`
Expected: a collection error, `ImportError: cannot import name 'manifest' from 'badshop.engine'`.

- [ ] **Step 3: Raise rembg's floor to the locked version**

`manifest.asset_path` (Step 5) relies on `BaseSession.model_dir()` and rembg's `<home>/models/<name>` layout, and
this plan checked both against rembg 2.0.85, the version `core/uv.lock` already pins. Plan 1's bare `"rembg[cpu]"`
accepts any rembg, for example an older one already installed in a user's environment, so the floor becomes the
locked version.

In `core/pyproject.toml`, replace:
```toml
    "opencv-python-headless>=4.8,<5",  # 5.x dropped the Haar cascades used for cat faces
    "rembg[cpu]",
    "pydantic>=2.7,<3",
```
with:
```toml
    "opencv-python-headless>=4.8,<5",  # 5.x dropped the Haar cascades used for cat faces
    "rembg[cpu]>=2.0.85",  # manifest.asset_path relies on BaseSession.model_dir() and models/<name>
    "pydantic>=2.7,<3",
```

Run: `cd core && uv lock`
Expected: `Resolved 42 packages in ...`. The locked rembg already satisfies the floor, so no package moves (rembg
stays 2.0.85); only the project's own `requires-dist` entry in `core/uv.lock` changes.

Run: `cd core && git diff --numstat uv.lock && git diff -U0 uv.lock | grep '^[-+] '`
Expected: exactly
```
1	1	core/uv.lock
-    { name = "rembg", extras = ["cpu"] },
+    { name = "rembg", extras = ["cpu"], specifier = ">=2.0.85" },
```
Any other changed line means `uv lock` moved a package, which this task must not do: restore the lock with
`git checkout uv.lock` and stop to report it. Then `cd core && uv lock --check` passes. Tasks 10 and 12's `uv add`
keep this line and its comment as they are.

- [ ] **Step 4: Add the progress listener, md5 and dest to `cached()`**

In `core/src/badshop/engine/assets.py`, make these five replacements.

(a) The hooks. Replace:
```python
# Called with the first URL of every request and with every redirect hop; it raises (EngineError, say)
# to refuse one. The CLI leaves it unset; the app installs a policy that refuses private addresses.
URL_POLICY: Callable[[str], None] | None = None
```
with:
```python
# Called with the first URL of every request and with every redirect hop; it raises (EngineError, say)
# to refuse one. The CLI leaves it unset; the app installs a policy that refuses private addresses.
URL_POLICY: Callable[[str], None] | None = None

# Called by cached() after every chunk of every download, as (name, bytes so far, total or None), on
# whichever thread is downloading; it must not raise (that aborts the download). The CLI leaves it
# unset; the app forwards it to clients as asset.progress events.
PROGRESS: Callable[[str, int, int | None], None] | None = None
```

(b) The signature, docstring and destination. Replace:
```python
def cached(name: str, url: str, progress: Callable[[int, int | None], None] | None = None,
           sha256: str | None = None, size: int | None = None) -> Path:
    """Download `url` once into data_dir()/name and reuse it. Raises EngineError when offline, when
    the download is cut short, or when it isn't the pinned file (`size` bytes hashing to `sha256`);
    nothing is kept then. A cached file of the wrong size (cut short by an older version) is
    downloaded again.

    Each call streams into its own temp file and renames it into place, so concurrent
    downloads of one name (threads or processes) never share a partial file."""
    path = data_dir() / name
```
with:
```python
def cached(name: str, url: str, progress: Callable[[int, int | None], None] | None = None,
           sha256: str | None = None, size: int | None = None, md5: str | None = None,
           dest: Path | None = None) -> Path:
    """Download `url` once into `dest` (an absolute path; default data_dir()/name) and reuse it. Raises
    EngineError when offline, when the download is cut short, or when it isn't the pinned file (`size`
    bytes hashing to `sha256` and/or `md5`); nothing is kept then. A cached file of the wrong size (cut
    short by an older version) is downloaded again. `progress(done, total)` and the process-wide
    PROGRESS(name, done, total) hear about every chunk.

    Each call streams into its own temp file and renames it into place, so concurrent
    downloads of one name (threads or processes) never share a partial file."""
    path = dest if dest is not None else data_dir() / name
```

(c) The md5 digest. Replace:
```python
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as fh:
```
with:
```python
            digest = hashlib.sha256()
            md5_digest = hashlib.md5(usedforsecurity=False) if md5 is not None else None  # rembg pins md5
            with os.fdopen(fd, "wb") as fh:
```

(d) The chunk loop. Replace:
```python
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if size is not None and done > size:
                        raise _not_pinned(name, f"it is bigger than the expected {size} bytes")
                    if progress:
                        progress(done, total)
```
with:
```python
                    fh.write(chunk)
                    digest.update(chunk)
                    if md5_digest is not None:
                        md5_digest.update(chunk)
                    done += len(chunk)
                    if size is not None and done > size:
                        raise _not_pinned(name, f"it is bigger than the expected {size} bytes")
                    if progress:
                        progress(done, total)
                    if PROGRESS is not None:
                        PROGRESS(name, done, total)
```

(e) The md5 check. Replace:
```python
            if sha256 is not None and digest.hexdigest() != sha256:
                raise _not_pinned(name, "it failed its checksum")
```
with:
```python
            if sha256 is not None and digest.hexdigest() != sha256:
                raise _not_pinned(name, "it failed its checksum")
            if md5_digest is not None and md5_digest.hexdigest() != md5:
                raise _not_pinned(name, "it failed its checksum")
```

- [ ] **Step 5: Write the manifest**

`core/src/badshop/engine/manifest.py`:
```python
"""Every file badshop downloads on first use: the fonts, the face detector and the background removers.
The app lists them (assets.status), pre-downloads them (assets.download) and maps assets.PROGRESS
events back to them by name."""

from dataclasses import dataclass
from pathlib import Path

from badshop.engine import assets, faces, text
from badshop.engine.errors import EngineError


@dataclass(frozen=True)
class Asset:
    name: str  # exactly the name cached() is called with, so PROGRESS events map to assets
    label: str  # what Settings shows
    url: str
    approx_mb: int
    size: int | None = None
    sha256: str | None = None
    md5: str | None = None  # rembg pins its models by md5
    rembg_model: str | None = None  # set for rembg's models, which live where rembg looks for them


_ANTON = text.FONT_DOWNLOADS["Anton-Regular.ttf"]
_COMIC = text.FONT_DOWNLOADS["ComicNeue-Bold.ttf"]
# rembg's own release files, URLs and md5s as in rembg's session classes (a test compares them).
# Each is stored as <model>.onnx: birefnet-general comes from BiRefNet-general-epoch_244.onnx.
_REMBG = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"

ASSETS: tuple[Asset, ...] = (
    Asset("fonts/Anton-Regular.ttf", "Anton font (an Impact lookalike)", _ANTON.url, 1,
          size=_ANTON.size, sha256=_ANTON.sha256),
    Asset("fonts/ComicNeue-Bold.ttf", "Comic Neue Bold font (a Comic Sans lookalike)", _COMIC.url, 1,
          size=_COMIC.size, sha256=_COMIC.sha256),
    Asset("face_detection_yunet_2023mar.onnx", "YuNet face finder", faces.YUNET.url, 1,
          size=faces.YUNET.size, sha256=faces.YUNET.sha256),
    Asset("rembg/u2net.onnx", "U2-Net background remover (the default)", _REMBG + "u2net.onnx", 168,
          size=175997641, md5="60024c5c889badc19c04ad937298a77b", rembg_model="u2net"),
    Asset("rembg/u2net_human_seg.onnx", "U2-Net background remover for people",
          _REMBG + "u2net_human_seg.onnx", 168,
          size=175997641, md5="c09ddc2e0104f800e3e1bb4652583d1f", rembg_model="u2net_human_seg"),
    Asset("rembg/isnet-anime.onnx", "IS-Net background remover for cartoons",
          _REMBG + "isnet-anime.onnx", 168,
          size=176069933, md5="6f184e756bb3bd901c8849220a83e38e", rembg_model="isnet-anime"),
    Asset("rembg/birefnet-general.onnx", "BiRefNet background remover (cleaner edges, large)",
          _REMBG + "BiRefNet-general-epoch_244.onnx", 928,
          size=972666916, md5="7a35a0141cbbc80de11d9c9a28f52697", rembg_model="birefnet-general"),
)


def get_asset(name: str) -> Asset:
    for a in ASSETS:
        if a.name == name:
            return a
    raise EngineError(f"unknown asset {name!r}", hint=f"assets: {', '.join(a.name for a in ASSETS)}")


def _session_class(model: str):
    """rembg's session class for `model`, found the way rembg.new_session finds it."""
    assets.configure_rembg()  # before rembg reads REMBG_HOME / U2NET_HOME
    from rembg.sessions import sessions_class

    for cls in sessions_class:
        if cls.name() == model:
            return cls
    raise EngineError(f"this rembg has no {model} model", hint="update rembg, or use another model")


def asset_path(a: Asset) -> Path:
    """Where the asset lives once downloaded. A rembg model goes where its session class looks first
    (<model_dir>/<model>.onnx), so rembg finds it and never downloads it itself."""
    if a.rembg_model is None:
        return assets.data_dir() / a.name
    return Path(_session_class(a.rembg_model).model_dir()) / f"{a.rembg_model}.onnx"


def is_present(a: Asset) -> bool:
    """True when cached() would not download it (the same test: a file of the pinned size)."""
    path = asset_path(a)
    return path.is_file() and (a.size is None or path.stat().st_size == a.size)


def status() -> list[dict]:
    return [{"name": a.name, "label": a.label, "approx_mb": a.approx_mb, "present": is_present(a)}
            for a in ASSETS]


def _fetch(a: Asset) -> Path:
    return assets.cached(a.name, a.url, sha256=a.sha256, size=a.size, md5=a.md5, dest=asset_path(a))


def download(name: str) -> Path:
    """Download one asset now (a cache hit when present); progress goes to assets.PROGRESS."""
    return _fetch(get_asset(name))


def ensure_rembg_model(model: str) -> Path:
    """rembg's weights for `model`, downloaded through cached() (progress, pinned size and md5) into the
    file rembg's session class opens, so rembg's own downloader (pooch) never runs or prints."""
    for a in ASSETS:
        if a.rembg_model == model:
            return _fetch(a)
    offered = ", ".join(a.rembg_model for a in ASSETS if a.rembg_model)
    raise EngineError(f"{model} is not a background remover badshop offers", hint=f"models: {offered}")
```

`manifest` imports `text` and `faces`, and `cutout` imports `manifest`. Neither `text` nor `faces` imports `cutout`
or `manifest`, so there is no import cycle. `assets` must never import `manifest`.

- [ ] **Step 6: Cache rembg sessions in `cutout`**

In `core/src/badshop/engine/cutout.py`, make these three replacements.

(a) The import. Replace:
```python
from badshop.engine import assets
```
with:
```python
from badshop.engine import manifest
```

(b) After the model list. Replace:
```python
RembgModel = Literal["u2net", "u2net_human_seg", "isnet-anime", "birefnet-general"]
```
with:
```python
RembgModel = Literal["u2net", "u2net_human_seg", "isnet-anime", "birefnet-general"]

_SESSIONS: dict[str, object] = {}  # model -> rembg session; at most one, kept until another model is used


def rembg_session(model: str) -> object:
    """rembg's session for `model`, reused while the process lives: building one takes 1-2 s and about
    400 MB of memory (birefnet-general several times that), so only the last model used stays loaded.
    The weights come through manifest.ensure_rembg_model, so a first download reports progress and
    rembg's own downloader never runs or prints."""
    session = _SESSIONS.get(model)
    if session is not None:
        return session
    drop_sessions()  # free the other model before loading this one
    try:
        manifest.ensure_rembg_model(model)  # imports rembg, after pointing it at our data dir
        from rembg import new_session
    except ImportError:
        raise EngineError("rembg is not installed", hint='pip install "rembg[cpu]", or use no_ai') from None
    except EngineError as e:  # the download failed: same message as any asset download, plus no_ai
        raise EngineError(e.message, hint=f"{e.hint}, or use no_ai" if e.hint else "use no_ai") from e
    try:
        session = new_session(model)
    # OSError: the weights vanished after the download and rembg's own download failed (requests'
    # errors are OSErrors). ValueError: rembg's own checksum check failed then.
    except (OSError, ValueError) as e:
        raise EngineError(f"couldn't download the {model} background-removal model ({e})",
                          hint="check the internet connection; it is only downloaded once, "
                               "or use no_ai") from None
    _SESSIONS[model] = session
    return session


def drop_sessions() -> None:
    """Forget every cached rembg session (frees their memory once nothing else holds them)."""
    _SESSIONS.clear()
```

(c) The background-removal branch of `cutout()`. Replace:
```python
    else:
        try:
            assets.configure_rembg()
            from rembg import new_session, remove
        except ImportError:
            raise EngineError("rembg is not installed",
                              hint='pip install "rembg[cpu]", or use no_ai') from None
        try:
            session = new_session(p.model)
        # OSError: offline, or the first-run model download failed (requests' errors are OSErrors).
        # ValueError: pooch's checksum check failed, e.g. a Wi-Fi login page came back instead of the model.
        # (new_session's other ValueError, an unknown model, can't happen: RembgModel is a Literal.)
        except (OSError, ValueError) as e:
            raise EngineError(f"couldn't download the {p.model} background-removal model ({e})",
                              hint="check the internet connection; it is only downloaded once, "
                                   "or use no_ai") from None
        mask = remove(piece.convert("RGB"), session=session).getchannel("A")
```
with:
```python
    else:
        session = rembg_session(p.model)
        from rembg import remove  # importable: rembg_session imported rembg

        mask = remove(piece.convert("RGB"), session=session).getchannel("A")
```

- [ ] **Step 7: Run the tests**

Run: `cd core && uv run pytest tests/test_manifest.py tests/test_cutout_paste.py -q`
Expected: all PASS (`35 passed`: this task's 19, and `test_cutout_paste.py`'s remaining 16, including
`test_cutout_rembg_parity`, which shows the CLI's cutout bytes and stdout did not change).

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check . && uv lock --check`
Expected: `955 passed, 1 deselected` (Task 3's 938, minus the 2 deleted tests, plus these 19; the deselected one is
the `network` test). Ruff prints `All checks passed!`, and `uv lock --check` prints `Resolved 42 packages in ...`
(the lock matches Step 3's floor).
`test_golden.py`'s `cutout-rembg` case passing shows the cached session gives the same pixels.

- [ ] **Step 8: Commit**

```bash
git add core/pyproject.toml core/uv.lock \
        core/src/badshop/engine/assets.py core/src/badshop/engine/manifest.py core/src/badshop/engine/cutout.py \
        core/tests/test_manifest.py core/tests/test_cutout_paste.py
git commit -m "feat(assets): asset manifest, download progress, rembg models through cached()

engine/manifest.py lists every first-use download (fonts, YuNet, the four rembg
models) with its URL, pinned size and hash, and offers status, download and
ensure_rembg_model. assets.PROGRESS hears every chunk of every download, and
cached() gains md5 and dest. rembg's weights now download through cached() into
the file rembg's session class opens, so pooch never runs or prints. cutout keeps
the last model's rembg session for the life of the process.

rembg's floor is now the locked 2.0.85 (rembg[cpu]>=2.0.85): asset_path relies on
BaseSession.model_dir() and the models/<name> layout. uv.lock moves no package.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

---

### Task 5: Session data model, artifact store and image import (and files.py)

**Files:**
- Create: `core/src/badshop/files.py`, `core/src/badshop/session/__init__.py`, `core/src/badshop/session/models.py`, `core/src/badshop/session/artifacts.py`; `core/tests/test_artifacts.py`
- Modify: `core/src/badshop/cli/filestore.py` (`final_path` moves to `badshop/files.py` and is imported back), `core/src/badshop/cli/main.py` (`final_dir()` uses `files.default_output_dir()`)
- Test: `core/tests/test_artifacts.py`

**Interfaces:**
- Consumes (Plan 1 code, unchanged by Tasks 1-4):
  - `badshop.engine.common.load_image(src: Path | bytes, formats: tuple[str, ...] | None = None, max_pixels: int | None = None) -> Image.Image` (upright, fully loaded, `.format` kept; over `max_pixels` raises `Image.DecompressionBombError`), `common.fit(im, longest) -> tuple[Image.Image, float]`, `common.has_alpha(im) -> bool`, `common.to_rgb(im) -> Image.Image`
  - `badshop.engine.sources.slugify(text) -> str` (lowercase `[a-z0-9_]`, at most 30 chars, `"fetch"` when empty)
  - `badshop.engine.result.EXT: dict[str, str]` (`PNG .png, JPEG .jpg, GIF .gif, WEBP .webp`)
  - `badshop.engine.errors.EngineError(message: str, hint: str | None = None)`
  - `badshop.cli.filestore.final_path(final_dir: Path, stem: str, ext: str) -> Path` and `badshop.cli.main.final_dir() -> Path` (moved/rewired here)
- Produces:
  - `badshop/files.py`: `default_output_dir() -> Path` (`$BADSHOP_OUT`, else `~/Pictures/badshop`; an empty `$BADSHOP_OUT` counts as unset, as before); `final_path(final_dir: Path, stem: str, ext: str) -> Path` (moved verbatim; `badshop.cli.filestore.final_path` is the same object, and `cli.main.final_dir()` returns `default_output_dir()`)
  - `badshop/session/models.py` (pydantic v2): `SCHEMA = 1`; `ImageFormat = Literal["PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF"]`; `EXT: dict[str, str]` (engine `EXT` plus `BMP .bmp`, `TIFF .tiff`); `StepStatus = Literal["proposed", "approved", "running", "done", "error", "rejected", "stale"]`;
    `Source(kind: str, url: str | None = None, page: str | None = None, title: str | None = None, license: str | None = None, creator: str | None = None)` (frozen);
    `ArtifactMeta(id: str (^[0-9a-f]{64}$), label: str, width: int, height: int, format: ImageFormat, mime: str, frames: int = 1, produced_by: str | None = None, source: Source | None = None, original_id: str | None = None)` (frozen) with property `ext -> str` (`EXT[format]`);
    `StepError(message: str, hint: str | None = None)`;
    `Step(id: str, index: int, tool: str, params: dict, actor: str, status: StepStatus, outputs: list[str] = [], result_text: str = "", data: dict | None = None, error: StepError | None = None, reason: str | None = None, edited: bool = False, started_at: float | None = None, finished_at: float | None = None, cache_key: str | None = None)`;
    `Part(type: Literal["text", "image"], text: str | None = None, artifact_id: str | None = None)`;
    `Message(id: str, role: Literal["user", "assistant", "system_note"], content: list[Part], step_ids: list[str] = [])`;
    `SessionData(schema_: int = SCHEMA (alias "schema"), id: str, name: str, created_at: float, provider_profile_id: str | None = None, approval_mode: Literal["auto", "ask_changes", "ask_all"] = "ask_changes", messages: list[Message] = [], steps: list[Step] = [], artifacts: dict[str, ArtifactMeta] = {}, transcript: list[dict] = [])` with `populate_by_name=True`; always dump with `model_dump(mode="json", by_alias=True)`
  - `badshop/session/artifacts.py`: `IMPORT_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF")`, `MAX_IMPORT_PIXELS = 100_000_000` (every artifact, not only imports), `WORKING_MAX = 1000`, `MIME: dict[str, str]`, `FORMAT_ALIASES = {"MPO": "JPEG"}`, `MIN_PREFIX = 6`, `REF_HINT = "use an artifact id from a tool result, like a3f9c1d2"`, `FORMATS_HINT`;
    `short(id: str) -> str` (first 8 chars); `describe(meta: ArtifactMeta) -> str` (`"a3f9c1d2 (lincoln_work, 761x1000)"`);
    `class ArtifactStore:` `__init__()` (empty); `meta: dict[str, ArtifactMeta]` (insertion order); `__contains__(id) -> bool`; `ids() -> list[str]`;
    `add(data: bytes, label: str, *, produced_by: str | None = None, source: Source | None = None, original_id: str | None = None) -> ArtifactMeta` (id = sha256 of the bytes; bytes already stored return the existing meta unchanged; bytes that don't open through `IMPORT_FORMATS`, or have more than `MAX_IMPORT_PIXELS`, raise `EngineError` and store nothing; width/height are upright; MPO is stored as `"JPEG"`);
    `data(id: str) -> bytes` and `image(id: str) -> Image.Image` (full ids only; unknown → `EngineError(f"no such artifact: {id}", hint=REF_HINT)`; `image` is a fresh upright decode, first frame of an animation);
    `resolve(ref: str) -> str` (full id or unique prefix of ≥ 6 hex chars, case-insensitive, surrounding whitespace ignored; no match → `EngineError(f"no such artifact: {ref}", hint=REF_HINT)`; several matches → `EngineError(f"artifact id {ref} is ambiguous (N artifacts start with it)", hint="give more characters of the id")`; never touches the filesystem);
    `drop(ids: Iterable[str]) -> None` (unknown ids ignored);
    `import_image(data: bytes, label: str, source: Source | None = None, *, produced_by: str | None = None) -> tuple[ArtifactMeta, ArtifactMeta]` (working copy, original; `produced_by` goes on every artifact the call stores: the original and the working copy, or the one artifact that is both halves when a small upright PNG is its own working copy; `None`, the default, is the user's own import, and Task 7 passes the step id for a source tool's pictures; bytes already stored keep their first meta, as with `add`)

- [ ] **Step 1: Write the failing tests**

`core/tests/test_artifacts.py`:
```python
import builtins
import hashlib
import io
import json
import os
import subprocess
import sys
import typing
from pathlib import Path

import pytest
from PIL import EpsImagePlugin, Image, UnidentifiedImageError
from pydantic import ValidationError

from badshop import files
from badshop.cli import filestore
from badshop.cli import main as cli_main
from badshop.engine.errors import EngineError
from badshop.session import artifacts
from badshop.session.artifacts import (IMPORT_FORMATS, MIME, REF_HINT, WORKING_MAX, ArtifactStore, describe,
                                       short)
from badshop.session.models import (EXT, SCHEMA, ArtifactMeta, ImageFormat, Message, Part, SessionData,
                                    Source, Step, StepError)

EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"


def encode(im: Image.Image, fmt: str = "PNG", **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def gif3() -> bytes:
    frames = [Image.new("RGB", (30, 20), c) for c in ("red", "lime", "blue")]
    return encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)


# --- files.py: the output folder rule and never-overwrite names, shared by the CLI and sessions ---

def test_final_path_lives_in_files_and_the_cli_still_exports_it(tmp_path):
    assert filestore.final_path is files.final_path
    first = files.final_path(tmp_path / "out", "lincoln", ".png")
    assert first == tmp_path / "out" / "lincoln.png"
    first.write_bytes(b"x")
    assert files.final_path(tmp_path / "out", "lincoln", ".png") == tmp_path / "out" / "lincoln_2.png"
    with pytest.raises(EngineError, match="bad file name"):
        files.final_path(tmp_path / "out", "../x", ".png")


def test_default_output_dir_is_the_cli_rule(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "mine"))
    assert files.default_output_dir() == tmp_path / "mine"
    assert cli_main.final_dir() == tmp_path / "mine"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("BADSHOP_OUT", "")  # set but empty: the default, as before
    assert files.default_output_dir() == tmp_path / "home" / "Pictures" / "badshop"
    monkeypatch.delenv("BADSHOP_OUT")
    assert files.default_output_dir() == tmp_path / "home" / "Pictures" / "badshop"
    assert cli_main.final_dir() == tmp_path / "home" / "Pictures" / "badshop"


# --- models.py ---

def test_session_data_saves_schema_under_its_alias_and_round_trips():
    aid = "a" * 64
    meta = ArtifactMeta(id=aid, label="lincoln_work", width=457, height=600, format="PNG", mime="image/png",
                        source=Source(kind="openverse", url="https://x.test/y.jpg", license="CC BY 2.0"))
    step = Step(id="s1", index=1, tool="cutout", params={"image": aid, "box": [1, 2, 30, 40]},
                actor="agent:fake", status="error", error=StepError(message="box is empty", hint="use find"))
    msg = Message(id="m1", role="user",
                  content=[Part(type="text", text="hi"), Part(type="image", artifact_id=aid)])
    data = SessionData(id="x1", name="Untitled", created_at=1.5, messages=[msg], steps=[step],
                       artifacts={aid: meta}, transcript=[{"role": "user", "content": "hi"}])
    dumped = data.model_dump(mode="json", by_alias=True)
    assert dumped["schema"] == SCHEMA == 1 and "schema_" not in dumped
    assert dumped["approval_mode"] == "ask_changes" and dumped["provider_profile_id"] is None
    assert dumped["steps"][0]["outputs"] == [] and dumped["steps"][0]["edited"] is False
    back = SessionData.model_validate_json(json.dumps(dumped))
    assert back == data and back.artifacts[aid].ext == ".png"
    assert SessionData.model_validate({**dumped, "schema": 7}).schema_ == 7  # by alias (session.json)
    assert SessionData(schema_=2, id="x", name="n", created_at=0).schema_ == 2  # and by name


def test_models_import_without_warnings():
    # a field called `schema` would shadow BaseModel.schema (a UserWarning); -W error fails on any warning
    p = subprocess.run([sys.executable, "-W", "error", "-c", "import badshop.session.artifacts"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr


def test_artifact_meta_is_frozen_and_validated():
    meta = ArtifactMeta(id="b" * 64, label="x", width=1, height=1, format="GIF", mime="image/gif")
    with pytest.raises(ValidationError):
        meta.produced_by = "s9"
    for bad_id in ("../../etc/passwd", "B" * 64, "b" * 63):
        with pytest.raises(ValidationError):
            ArtifactMeta(id=bad_id, label="x", width=1, height=1, format="PNG", mime="image/png")
    with pytest.raises(ValidationError):
        ArtifactMeta(id="b" * 64, label="x", width=1, height=1, format="EPS", mime="application/postscript")
    with pytest.raises(ValidationError):
        Step(id="s1", index=1, tool="info", params={}, actor="user", status="finished")


def test_every_import_format_has_an_extension_and_a_mime_type():
    assert set(typing.get_args(ImageFormat)) == set(IMPORT_FORMATS) == set(MIME) == set(EXT)
    assert {f: EXT[f] for f in IMPORT_FORMATS} == {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif",
                                                    "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff"}


# --- ArtifactStore.add / data / image / drop ---

def test_add_stores_bytes_under_their_sha256():
    store = ArtifactStore()
    data = encode(Image.new("RGB", (30, 20), "red"))
    meta = store.add(data, "red", produced_by="s1")
    assert meta.id == hashlib.sha256(data).hexdigest()
    assert (meta.label, meta.width, meta.height, meta.format, meta.mime, meta.frames, meta.ext) == \
        ("red", 30, 20, "PNG", "image/png", 1, ".png")
    assert (meta.produced_by, meta.source, meta.original_id) == ("s1", None, None)
    assert meta.id in store and "red" not in store and store.ids() == [meta.id]
    assert store.meta[meta.id] is meta
    assert store.data(meta.id) == data
    with store.image(meta.id) as im:
        assert im.size == (30, 20) and im.getpixel((0, 0)) == (255, 0, 0)
    assert short(meta.id) == meta.id[:8] and describe(meta) == f"{meta.id[:8]} (red, 30x20)"


def test_the_same_bytes_keep_their_first_meta():
    # store half of Review Focus 2: an output produced again (or re-imported) keeps its first produced_by
    store = ArtifactStore()
    data = encode(Image.new("RGBA", (10, 10), (0, 0, 255, 128)))
    first = store.add(data, "lincoln_cutout", produced_by="s2")
    again = store.add(data, "other", produced_by="s5", source=Source(kind="url", url="https://x.test/a.png"))
    assert again is first and store.ids() == [first.id]
    assert (again.label, again.produced_by, again.source) == ("lincoln_cutout", "s2", None)


@pytest.mark.parametrize("fmt", IMPORT_FORMATS)
def test_add_records_each_format(fmt):
    store = ArtifactStore()
    meta = store.add(encode(Image.new("RGB", (8, 6), "white"), fmt), "x")
    assert (meta.format, meta.mime, meta.ext, meta.width, meta.height) == (fmt, MIME[fmt], EXT[fmt], 8, 6)


def test_add_counts_frames_and_stores_a_phone_mpo_as_jpeg():
    store = ArtifactStore()
    gif = store.add(gif3(), "anim")
    assert (gif.format, gif.frames, gif.ext) == ("GIF", 3, ".gif")
    left, right = Image.new("RGB", (16, 12), "red"), Image.new("RGB", (16, 12), "blue")
    mpo = store.add(encode(left, "MPO", save_all=True, append_images=[right]), "phone")
    assert (mpo.format, mpo.mime, mpo.ext, mpo.frames) == ("JPEG", "image/jpeg", ".jpg", 2)


def test_add_refuses_what_is_not_an_image():
    store = ArtifactStore()
    png = encode(Image.new("RGB", (64, 64), "red"))
    for bad in (b"", b"not an image", EPS, png[: len(png) // 2]):
        with pytest.raises(EngineError, match="isn't an image badshop can open") as e:
            store.add(bad, "x")
        assert e.value.hint and "BytesIO" not in e.value.message
    assert store.ids() == []


def test_unknown_ids_are_clean_errors_and_drop_forgets():
    store = ArtifactStore()
    keep = store.add(encode(Image.new("RGB", (4, 4), "red")), "keep")
    gone = store.add(encode(Image.new("RGB", (4, 4), "blue")), "gone")
    store.drop([gone.id, "0" * 64])  # unknown ids are ignored
    assert store.ids() == [keep.id] and gone.id not in store
    for call in (store.data, store.image):
        with pytest.raises(EngineError, match=f"no such artifact: {gone.id}") as e:
            call(gone.id)
        assert e.value.hint == REF_HINT


def test_the_eps_decoder_is_never_reached(monkeypatch):
    reached = []
    monkeypatch.setattr(EpsImagePlugin.EpsImageFile, "_open", lambda self: reached.append(1))
    with pytest.raises(UnidentifiedImageError):
        Image.open(io.BytesIO(EPS))  # with every decoder on, Pillow hands these bytes to EPS (Ghostscript)
    assert reached == [1]
    store = ArtifactStore()
    for call in (lambda: store.add(EPS, "x"), lambda: store.import_image(EPS, "x.eps")):
        with pytest.raises(EngineError, match="isn't an image badshop can open"):
            call()
    assert reached == [1] and store.ids() == []


# --- ArtifactStore.resolve ---

def test_resolve_takes_full_ids_and_unique_prefixes():
    store = ArtifactStore()
    meta = store.add(encode(Image.new("RGB", (4, 4), "red")), "x")
    for ref in (meta.id, meta.id.upper(), meta.id[:8], meta.id[:6], meta.id[:6].upper(), f" {meta.id[:8]} "):
        assert store.resolve(ref) == meta.id


def test_resolve_refuses_everything_else_without_touching_the_disk(monkeypatch, tmp_path):
    store = ArtifactStore()
    meta = store.add(encode(Image.new("RGB", (4, 4), "red")), "x")
    real = tmp_path / "real.png"
    real.write_bytes(store.data(meta.id))
    refs = [str(real), "real.png", "../../etc/passwd", "https://example.com/x.png", "", meta.id[:5],
            meta.id[:8] + "zz", "0" * 64]

    def no_disk(*a, **k):
        raise AssertionError("resolve touched the filesystem")

    errors = []
    with monkeypatch.context() as m:
        for name in ("open", "stat", "lstat", "listdir", "scandir"):
            m.setattr(os, name, no_disk)
        m.setattr(builtins, "open", no_disk)
        for ref in refs:
            try:
                store.resolve(ref)
            except EngineError as e:
                errors.append((e.message, e.hint))
    assert errors == [(f"no such artifact: {ref}", REF_HINT) for ref in refs]


def test_resolve_refuses_an_ambiguous_prefix():
    store = ArtifactStore()
    for i in "01":
        aid = "abcdef" + i * 58
        store.meta[aid] = ArtifactMeta(id=aid, label=i, width=1, height=1, format="PNG", mime="image/png")
    with pytest.raises(EngineError, match="ambiguous") as e:
        store.resolve("ABCDEF")
    assert "more characters" in e.value.hint
    assert store.resolve("abcdef1") == "abcdef" + "1" * 58


# --- ArtifactStore.import_image ---

def test_import_makes_a_working_copy_and_keeps_the_original_bytes():
    store = ArtifactStore()
    photo = encode(Image.new("RGB", (3000, 1500), "green"), "JPEG", quality=90)
    src = Source(kind="clipboard")
    working, original = store.import_image(photo, "/home/u/Pictures/Holiday Photo.JPG", source=src)
    assert (original.label, original.format, original.mime, original.ext) == \
        ("holiday_photo", "JPEG", "image/jpeg", ".jpg")
    assert (original.width, original.height) == (3000, 1500) and store.data(original.id) == photo
    assert (working.label, working.format, working.width, working.height) == \
        ("holiday_photo_work", "PNG", 1000, 500)
    assert working.original_id == original.id and working.source == original.source == src
    assert working.produced_by is None and original.original_id is None
    assert describe(working) == f"{working.id[:8]} (holiday_photo_work, 1000x500)"
    with store.image(working.id) as im:
        assert im.mode == "RGB" and max(im.size) == WORKING_MAX
    again = store.import_image(photo, "renamed.jpg")  # the same file twice: nothing new
    assert again == (working, original) and store.ids() == [original.id, working.id]
    # a source tool's picture (Task 7): both halves are credited to the step that brought it in
    f_work, f_orig = ArtifactStore().import_image(photo, "holiday.jpg", src, produced_by="s4")
    assert f_work.produced_by == f_orig.produced_by == "s4" and f_work.original_id == f_orig.id
    assert f_work.source == f_orig.source == src
    assert store.import_image(photo, "x.jpg", produced_by="s9") == (working, original)  # stored: first meta wins
    with pytest.raises(TypeError):
        store.import_image(photo, "x.jpg", src, "s9")  # produced_by is keyword-only
    assert store.ids() == [original.id, working.id]


def test_a_badshop_png_is_its_own_working_copy():
    store = ArtifactStore()
    data = encode(Image.new("RGB", (50, 40), "red"))  # small, upright, PNG: what an import would make
    working, original = store.import_image(data, "lincoln_lasers.png")
    assert working is original and store.ids() == [working.id] and store.data(working.id) == data
    assert (working.label, working.original_id) == ("lincoln_lasers_work", None)
    scan, _ = store.import_image(encode(Image.new("RGB", (1200, 900), "red"), "BMP"), "scan.bmp")
    w, o = store.import_image(store.data(scan.id), "scan_work.png")  # an exported working copy, re-imported
    assert w is o is scan and len(store.ids()) == 3
    one, same = ArtifactStore().import_image(data, "emoji_1f602.png", produced_by="s7")  # still one
    assert one is same and (one.label, one.produced_by, one.original_id) == ("emoji_1f602_work", "s7", None)


def test_import_keeps_transparency_where_prep_would_flatten_it():
    store = ArtifactStore()
    sticker = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    sticker.paste((255, 0, 0, 255), (20, 0, 40, 20))
    working, _ = store.import_image(encode(sticker), "sticker.png")
    with store.image(working.id) as im:
        assert im.mode == "RGBA" and im.getpixel((5, 5))[3] == 0 and im.getpixel((30, 5)) == (255, 0, 0, 255)
    pal = Image.new("P", (10, 10), 0)
    pal.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    pal.paste(1, (5, 0, 10, 10))
    working, _ = store.import_image(encode(pal, "GIF", transparency=0), "emoji.gif")
    with store.image(working.id) as im:
        assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0
        assert im.getpixel((7, 5)) == (255, 255, 255, 255)


def test_import_takes_the_first_frame_of_an_animation():
    store = ArtifactStore()
    working, original = store.import_image(gif3(), "dance.gif")
    assert (original.format, original.frames) == ("GIF", 3)
    assert (working.format, working.frames, working.width, working.height) == ("PNG", 1, 30, 20)
    with store.image(working.id) as im:
        assert im.getpixel((0, 0)) == (255, 0, 0)


def test_import_turns_a_phone_photo_upright():
    store = ArtifactStore()
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to show
    photo = encode(Image.new("RGB", (40, 20), "blue"), "JPEG", exif=exif)
    working, original = store.import_image(photo, "IMG_0001.jpg")
    assert (working.width, working.height) == (20, 40) and (original.width, original.height) == (20, 40)
    assert store.data(original.id) == photo  # the original bytes, EXIF included, unchanged


@pytest.mark.parametrize("name, label", [
    ("lincoln.png", "lincoln"), ("Old Photo é.JPG", "old_photo"), ("/home/u/Pictures/trump.jpeg", "trump"),
    ("../../etc/passwd", "passwd"), ("fetch.png", "fetch"), ("", "pasted"), ("日本.png", "pasted"),
    ("badshop_work/lincoln_work.png", "lincoln"), ("work.png", "work"),
])
def test_import_labels_are_slugified_file_stems(name, label):
    working, original = ArtifactStore().import_image(encode(Image.new("RGB", (1200, 10), "gray")), name)
    assert (original.label, working.label) == (label, f"{label}_work")


def test_import_refuses_bad_bytes_cleanly_and_stores_nothing(monkeypatch):
    store = ArtifactStore()
    png = encode(Image.new("RGB", (64, 64), "red"))
    for bad in (b"", b"GIF89a garbage", EPS, png[: len(png) // 2]):
        with pytest.raises(EngineError, match="isn't an image badshop can open") as e:
            store.import_image(bad, "notes.txt")
        assert e.value.message.startswith("notes.txt ") and "PNG, JPEG" in e.value.hint
    monkeypatch.setattr(artifacts, "MAX_IMPORT_PIXELS", 100)  # a 20x20 image stands in for a >100 Mpx one
    with pytest.raises(EngineError, match="too big") as e:
        store.import_image(encode(Image.new("RGB", (20, 20))), "")
    assert e.value.message.startswith("the pasted data is too big") and "megapixels" in e.value.hint
    assert store.ids() == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_artifacts.py -q`
Expected: a collection error, `ImportError: cannot import name 'files' from 'badshop'`.

- [ ] **Step 3: Move `final_path` into `badshop/files.py` and point the CLI at it**

`core/src/badshop/files.py`:
```python
"""Where finished images go, shared by the CLI and sessions: the output folder and never-overwrite names."""

import os
from pathlib import Path

from badshop.engine.errors import EngineError


def default_output_dir() -> Path:
    """The user's output folder: $BADSHOP_OUT, else ~/Pictures/badshop (the CLI's rule since Plan 1)."""
    return Path(os.environ.get("BADSHOP_OUT") or Path.home() / "Pictures" / "badshop")


def final_path(final_dir: Path, stem: str, ext: str) -> Path:
    """Finished files never overwrite older ones: stem.ext, stem_2.ext, stem_3.ext...

    The stem must be a plain file name, so the file lands in final_dir itself. Params already refuse
    other names; this catches any caller that skipped them (a stem with a folder, a drive, or `..`)."""
    if stem in ("", ".", "..") or Path(stem).name != stem:  # this OS's separators and drives
        raise EngineError(f"bad file name {stem!r}: it must not contain folders",
                          hint="give a plain file name, e.g. lincoln_lasers")
    final_dir.mkdir(parents=True, exist_ok=True)
    p, i = final_dir / f"{stem}{ext}", 2
    while p.exists():
        p, i = final_dir / f"{stem}_{i}{ext}", i + 1
    return p
```

In `core/src/badshop/cli/filestore.py`, replace the imports' tail and the whole `final_path` function:
```python
from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output


def final_path(final_dir: Path, stem: str, ext: str) -> Path:
    """Finished files never overwrite older ones: stem.ext, stem_2.ext, stem_3.ext...

    The stem must be a plain file name, so the file lands in final_dir itself. Params already refuse
    other names; this catches any caller that skipped them (a stem with a folder, a drive, or `..`)."""
    if stem in ("", ".", "..") or Path(stem).name != stem:  # this OS's separators and drives
        raise EngineError(f"bad file name {stem!r}: it must not contain folders",
                          hint="give a plain file name, e.g. lincoln_lasers")
    final_dir.mkdir(parents=True, exist_ok=True)
    p, i = final_dir / f"{stem}{ext}", 2
    while p.exists():
        p, i = final_dir / f"{stem}_{i}{ext}", i + 1
    return p
```
with:
```python
from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.files import final_path  # moved to badshop.files (sessions use it too); still importable here
```
(`FileStore.put` and `FileStore.export` keep calling `final_path`, so the import is used and `tests/test_params.py`'s `from badshop.cli.filestore import final_path` keeps working. `Path` is still used by the rest of the file.)

In `core/src/badshop/cli/main.py`, replace:
```python
import argparse
import os
import sys
from pathlib import Path
```
with:
```python
import argparse
import sys
from pathlib import Path
```
replace:
```python
from badshop.engine.errors import EngineError
from badshop.tools import REGISTRY
```
with:
```python
from badshop.engine.errors import EngineError
from badshop.files import default_output_dir
from badshop.tools import REGISTRY
```
and replace:
```python
def final_dir() -> Path:
    return Path(os.environ.get("BADSHOP_OUT") or Path.home() / "Pictures" / "badshop")
```
with:
```python
def final_dir() -> Path:
    return default_output_dir()
```

- [ ] **Step 4: Implement the data model**

`core/src/badshop/session/__init__.py` (kept import-free, so the worker's child process can import `badshop.session.execution` without pulling in the rest):
```python
"""Sessions: artifacts, steps, replay, project files (spec §5.3, §6)."""
```

`core/src/badshop/session/models.py`:
```python
"""The session data model (spec §6). It is also session.json in a .badshop project file."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from badshop.engine.result import EXT as OUTPUT_EXT

SCHEMA = 1  # session.json's "schema"; bump it (and migrate older files) whenever the saved shape changes

ImageFormat = Literal["PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF"]
EXT: dict[str, str] = {**OUTPUT_EXT, "BMP": ".bmp", "TIFF": ".tiff"}  # tool outputs keep their CLI extensions

StepStatus = Literal["proposed", "approved", "running", "done", "error", "rejected", "stale"]


class Source(BaseModel):
    """Where a fetched or imported image came from (EngineResult.data["sources"] entries)."""

    model_config = ConfigDict(frozen=True)
    kind: str  # commons | openverse | wikipedia | imgflip | twemoji | url | clipboard
    url: str | None = None  # the URL that delivered the bytes
    page: str | None = None  # the page describing the image (licence, author)
    title: str | None = None
    license: str | None = None
    creator: str | None = None


class ArtifactMeta(BaseModel):
    """An immutable image. Frozen: an artifact produced twice keeps its first label and produced_by."""

    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=r"^[0-9a-f]{64}$")  # sha256 of the stored bytes
    label: str
    width: int
    height: int
    format: ImageFormat
    mime: str
    frames: int = 1
    produced_by: str | None = None  # step id
    source: Source | None = None
    original_id: str | None = None  # an import's working copy -> the full-size original it was made from

    @property
    def ext(self) -> str:
        return EXT[self.format]


class StepError(BaseModel):
    message: str
    hint: str | None = None


class Step(BaseModel):
    id: str  # "s1", "s2", ...
    index: int
    tool: str
    params: dict  # validated, JSON-safe; image refs are full artifact ids
    actor: str  # "user" | "agent:<provider>" | "cli:<claude|codex|gemini>"
    status: StepStatus
    outputs: list[str] = []
    result_text: str = ""
    data: dict | None = None
    error: StepError | None = None
    reason: str | None = None  # why the actor proposed it (shown with the approval)
    edited: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    cache_key: str | None = None


class Part(BaseModel):
    type: Literal["text", "image"]
    text: str | None = None
    artifact_id: str | None = None


class Message(BaseModel):
    id: str  # "m1", "m2", ...
    role: Literal["user", "assistant", "system_note"]
    content: list[Part]
    step_ids: list[str] = []


class SessionData(BaseModel):
    """The whole session. `schema` would shadow BaseModel.schema, so the field is `schema_` with the alias
    "schema": always dump with `by_alias=True` (session.json says "schema": 1)."""

    model_config = ConfigDict(populate_by_name=True)
    schema_: int = Field(SCHEMA, alias="schema")
    id: str
    name: str
    created_at: float
    provider_profile_id: str | None = None  # a profile id only: keys never go in the file
    approval_mode: Literal["auto", "ask_changes", "ask_all"] = "ask_changes"
    messages: list[Message] = []
    steps: list[Step] = []
    artifacts: dict[str, ArtifactMeta] = {}
    transcript: list[dict] = []  # the provider-format message history the agent resumes from
```

Notes:
- `ArtifactMeta` and `Source` are frozen: an artifact never changes after it is stored, and a second `add` of the same bytes returns the first meta (Review Focus 2's store half). Build a changed copy with `model_copy(update=...)` if a later plan ever needs one.
- `ArtifactMeta.id`'s pattern and `format`'s `Literal` mean a hostile `session.json` cannot smuggle a path-like id or an unknown format past `SessionData.model_validate` (Review Focus 3 support for Task 9), and `ext` can never raise `KeyError`.
- The six formats appear three times (`ImageFormat`, `IMPORT_FORMATS`, `MIME`); `test_every_import_format_has_an_extension_and_a_mime_type` keeps them in step with `EXT`.

- [ ] **Step 5: Implement the artifact store and image import**

`core/src/badshop/session/artifacts.py`:
```python
"""The session's images: immutable artifacts stored by the SHA-256 of their bytes (spec §5.3)."""

import hashlib
import io
import re
from collections.abc import Iterable
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError

from badshop.engine.common import fit, has_alpha, load_image, to_rgb
from badshop.engine.errors import EngineError
from badshop.engine.sources import slugify
from badshop.session.models import ArtifactMeta, Source

# The decoders an import may use: never EPS (it runs Ghostscript) or Pillow's rarer plugins (SEC-S1).
IMPORT_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF")
MAX_IMPORT_PIXELS = 100_000_000  # the most pixels any artifact may have; refused before decoding
WORKING_MAX = 1000  # an import's working copy: longest side in px, as `prep` makes
MIME: dict[str, str] = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp",
                        "BMP": "image/bmp", "TIFF": "image/tiff"}
FORMAT_ALIASES = {"MPO": "JPEG"}  # a phone's multi-picture JPEG opens as MPO; it is a JPEG file
MIN_PREFIX = 6
REF_HINT = "use an artifact id from a tool result, like a3f9c1d2"
FORMATS_HINT = "use a PNG, JPEG, GIF, WebP, BMP or TIFF image"


def short(id: str) -> str:
    return id[:8]


def describe(meta: ArtifactMeta) -> str:
    """How tool results and the step summary name an artifact: "a3f9c1d2 (lincoln_work, 761x1000)"."""
    return f"{short(meta.id)} ({meta.label}, {meta.width}x{meta.height})"


def _label(name: str) -> str:
    """A file name (or any text) as a label: its stem slugified, "pasted" when nothing usable is left, and
    without a trailing "_work", so re-importing badshop_work/lincoln_work.png is not lincoln_work_work."""
    stem = PurePath(name).stem if name else ""
    if not re.search(r"[a-z0-9]", stem.lower()):
        return "pasted"
    return re.sub(r"_work$", "", slugify(stem))


def _refused(name: str, e: Exception) -> EngineError:
    if isinstance(e, Image.DecompressionBombError):  # ours (over MAX_IMPORT_PIXELS) or Pillow's own limit
        return EngineError(f"{name} is too big ({e})", hint="use a smaller copy of the image "
                           f"(the limit is {MAX_IMPORT_PIXELS // 1_000_000} megapixels)")
    detail = "" if isinstance(e, UnidentifiedImageError) else f" ({e})"  # "cannot identify" names a BytesIO
    return EngineError(f"{name} isn't an image badshop can open{detail}", hint=FORMATS_HINT)


def _decode(data: bytes, name: str) -> Image.Image:
    """Bytes as an upright, fully loaded image, through the import decoders only. Hostile bytes can make
    a decoder raise almost anything (OSError, SyntaxError, ValueError, struct.error...): all become
    EngineError."""
    try:
        return load_image(data, formats=IMPORT_FORMATS, max_pixels=MAX_IMPORT_PIXELS)
    except Exception as e:
        raise _refused(name, e) from None


class ArtifactStore:
    """Artifact bytes and metadata. An id is always the sha256 of the bytes, computed here, never trusted."""

    def __init__(self):
        self.meta: dict[str, ArtifactMeta] = {}
        self._data: dict[str, bytes] = {}

    def __contains__(self, id: object) -> bool:
        return id in self.meta

    def ids(self) -> list[str]:
        return list(self.meta)

    def add(self, data: bytes, label: str, *, produced_by: str | None = None, source: Source | None = None,
            original_id: str | None = None) -> ArtifactMeta:
        """Store bytes as an artifact. Bytes already stored return the existing meta unchanged, so an
        artifact keeps the label, produced_by and source it was first stored with."""
        id = hashlib.sha256(data).hexdigest()
        if id in self.meta:
            return self.meta[id]
        with _decode(data, label) as im:  # only images that open are stored, so image() never fails later
            fmt = FORMAT_ALIASES.get(im.format, im.format)
            meta = ArtifactMeta(id=id, label=label, width=im.width, height=im.height, format=fmt,
                                mime=MIME[fmt], frames=getattr(im, "n_frames", 1), produced_by=produced_by,
                                source=source, original_id=original_id)
        self._data[id] = data
        self.meta[id] = meta
        return meta

    def data(self, id: str) -> bytes:
        try:
            return self._data[id]
        except KeyError:
            raise EngineError(f"no such artifact: {id}", hint=REF_HINT) from None

    def image(self, id: str) -> Image.Image:
        """A fresh decoded copy (upright; an animation is at its first frame)."""
        return _decode(self.data(id), self.meta[id].label)

    def resolve(self, ref: str) -> str:
        """A full id, or a unique prefix of at least 6 hex characters (any case), as the full id.
        Anything else, a path or URL included, is "no such artifact": this never touches the disk."""
        r = ref.strip().lower()
        if r in self.meta:
            return r
        if len(r) >= MIN_PREFIX and re.fullmatch(r"[0-9a-f]+", r):
            hits = [i for i in tuple(self.meta) if i.startswith(r)]  # tuple(): a snapshot across threads
            if len(hits) == 1:
                return hits[0]
            if hits:
                raise EngineError(f"artifact id {ref} is ambiguous ({len(hits)} artifacts start with it)",
                                  hint="give more characters of the id")
        raise EngineError(f"no such artifact: {ref}", hint=REF_HINT)

    def drop(self, ids: Iterable[str]) -> None:
        """Forget artifacts (ids not in the store are ignored)."""
        for id in list(ids):
            self.meta.pop(id, None)
            self._data.pop(id, None)

    def import_image(self, data: bytes, label: str, source: Source | None = None, *,
                     produced_by: str | None = None) -> tuple[ArtifactMeta, ArtifactMeta]:
        """A new image entering the session (a file, a drop, a paste, a fetched picture): returns
        (working copy, original).

        The working copy is what every tool sees: the first frame, upright, at most WORKING_MAX px, as PNG,
        keeping transparency (not `prep`, which flattens it). The original is the given bytes, unchanged,
        kept for provenance. Labels: "<name>_work" and "<name>" from the slugified file name stem.
        `produced_by` is the step that brought the picture in (a source tool's step), on every artifact
        this stores; None for the user's own import."""
        name = _label(label)
        with _decode(data, label or "the pasted data") as im:
            work, _ = fit(im.convert("RGBA") if has_alpha(im) else to_rgb(im), WORKING_MAX)
        buf = io.BytesIO()
        work.save(buf, "PNG")
        work_bytes = buf.getvalue()
        if work_bytes == data:  # a small upright PNG from badshop is its own working copy: stored once
            meta = self.add(data, f"{name}_work", produced_by=produced_by, source=source)
            return meta, meta
        original = self.add(data, name, produced_by=produced_by, source=source)
        working = self.add(work_bytes, f"{name}_work", produced_by=produced_by, source=source,
                           original_id=original.id)
        return working, original
```

Notes:
- `add` decodes what it stores (through `load_image` with `IMPORT_FORMATS` and `MAX_IMPORT_PIXELS`), so every artifact in a store opens: a tool never meets an undecodable artifact, and Task 9 can rebuild a store from a project file with `add(bytes, meta.label, produced_by=..., source=..., original_id=...)` and compare the result with `session.json`'s meta. The cost is one decode per stored output (milliseconds at working-copy size).
- The working copy uses `fit(im.convert("RGBA") if has_alpha(im) else to_rgb(im), WORKING_MAX)`, never `basic.prep` (CO M8: prep flattens transparency), and imports from bytes only (the carry-forward's GIF file-handle item). EPS and Pillow's other decoders are never tried (SEC-S1).
- Labels: the original is the slugified file-name stem (`"Holiday Photo.JPG"` → `holiday_photo`), the working copy adds `_work` (`holiday_photo_work`, as `prep` names it); a trailing `_work` is dropped first, so re-importing `badshop_work/lincoln_work.png` gives `lincoln` / `lincoln_work`, and a name with no ASCII letters or digits (a paste, `日本.png`) gives `pasted`.
- When the working copy's PNG bytes equal the given bytes (a small upright PNG that badshop made; with the locked Pillow the lincoln fixture is one), one artifact is stored, labelled `<name>_work` with `original_id=None`, and returned as both halves of the tuple, so the working copy's label never depends on whether Pillow's re-encode happened to match.
- `import_image`'s keyword-only `produced_by` goes on every `add` it makes: both halves, or the one artifact that is both. The user's own imports leave it `None`; Task 7 stores a source tool's pictures (`fetch`, `wiki`, `emoji`, `template`) with `import_image(data, label, source, produced_by=step.id)`, so a fetched picture names the step that fetched it. Bytes the store already holds keep their first meta, `produced_by` included, exactly as `add` does.
- `resolve` works only on the in-memory ids (a snapshot of the keys, so a concurrent `add` from another thread cannot break the iteration). Stored step params always hold full ids (Task 7 resolves before storing).
- Pillow still prints its `DecompressionBombWarning` for an import between about 89 and 100 megapixels before the import succeeds; the carry-forward leaves that to the worker.

- [ ] **Step 6: Run the tests**

Run: `cd core && uv run pytest tests/test_artifacts.py tests/test_params.py tests/test_cli.py tests/test_recipes.py -q`
Expected: `268 passed` (this task's 36, which alone pass in about a second, plus the 156 params, 41 CLI and 35
recipe tests that still reach `final_path` through `badshop.cli.filestore` and `final_dir()`).

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `991 passed, 1 deselected` (Task 4's 955 plus these 36; the deselected one is the `network` test), and
ruff prints `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add core/src/badshop/files.py core/src/badshop/session/__init__.py core/src/badshop/session/models.py \
  core/src/badshop/session/artifacts.py core/src/badshop/cli/filestore.py core/src/badshop/cli/main.py \
  core/tests/test_artifacts.py
git commit -m "feat(session): data model, artifact store and image import; files.py for output paths

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Tool-call boundary (ToolCall/ToolOutcome/BytesStore/execute_call) and the private-address URL policy

**Files:**
- Create: `core/src/badshop/session/netpolicy.py`, `core/src/badshop/session/execution.py`
- Test: `core/tests/test_execution.py`
- Modify: nothing. Plan 1 already calls `assets.URL_POLICY` on the first URL of every request
  (`assets._open`) and on every redirect hop (`_WebOnlyRedirects.redirect_request`); this task only
  installs a policy there.

**Interfaces:**
- Consumes:
  - Task 2: `runner.validate(name: str, raw: dict, actor: str = "user") -> Params`,
    `runner.execute(name: str, params: Params, store: Store, stem: str | None = None) -> ToolRun`,
    `runner.is_trusted(actor: str) -> bool`.
  - Task 5: the `badshop.session` package (`session/__init__.py`), `session.artifacts.IMPORT_FORMATS`,
    `session.artifacts.MAX_IMPORT_PIXELS`.
  - Plan 1: `assets.URL_POLICY`, `assets.http_get`, `common.load_image(src, formats=None, max_pixels=None)`,
    `EngineError(message, hint)`, `Output` (`key`, `name_hint`, `caption`, `encode()`), `EngineResult`,
    `registry.REGISTRY`, `registry.ToolSpec(name, params, run, summary, description, category, ...)`,
    `badshop.__version__`, `basic.prep` / `basic.PrepParams`, `sources.read_clipboard`; test helpers
    `conftest.FIXTURES`, `localweb.serve` / `localweb.response`, `test_downloads.pixel_bomb_png`.
- Produces:
  - `session/netpolicy.py`:
    - `refuse_private(url: str, trusted: frozenset[str] = frozenset()) -> None`: raises
      `EngineError(f"refused {url[:60]}: it points into this computer or the local network", hint=LOCAL_HINT)`
    - `policy_for(trusted: frozenset[str] = frozenset()) -> Callable[[str], None]`
    - `guarded(trusted: frozenset[str] = frozenset())`: a context manager that sets `assets.URL_POLICY` and restores the previous value
    - `typed_urls(tool: str, params: dict, actor: str) -> frozenset[str]`: new. It returns what the session passes as `ToolCall.trusted_urls`
    - constants `LOCAL_HINT`, `WEB_LINK`, `NAT64`
  - `session/execution.py`:
    - `@dataclass(frozen=True) ToolCall(tool: str, params: dict, inputs: dict[str, bytes], stem: str, trusted_urls: frozenset[str] = frozenset(), guard_network: bool = True)`
    - `@dataclass OutputRecord(key: str, data: bytes, name_hint: str, caption: str = "")`
    - `@dataclass ToolOutcome(ok: bool, outputs: list[OutputRecord] = [], lines: list[str] = [], data: dict = {}, error_message: str | None = None, error_hint: str | None = None, crashed: bool = False)`. The list and dict defaults use `default_factory`.
    - `class BytesStore(inputs: dict[str, bytes])` with `.outputs: list[OutputRecord]`, `load(ref) -> Image`, `put(output, stem) -> "out:<n>"` (0-based) and `export(ref, name)` (always raises `EngineError("export runs in the session")`)
    - `execute_call(call: ToolCall) -> ToolOutcome`
    - `json_safe(data: dict) -> dict`: the coercion `execute_call` applies to a tool's data. Tuples become
      lists, values JSON has no type for (a `Path`) become their `str()`, and non-finite floats (NaN, inf,
      -inf, numpy's included) become None
    - `cache_key(tool: str, params: dict) -> str`
    - `@runtime_checkable class Executor(Protocol)`: `run(call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome`,
      `cancel() -> None`, `close() -> None`. `cancel` is that one call's own stop signal: set before the call
      begins, the tool never runs; set while it runs, an executor that can stop a tool stops it. Either way
      the outcome is `ToolOutcome(ok=False, error_message=STOPPED)` (not crashed, no hint). `cancel()` stops
      whatever call is running at that moment, for callers with no event (the server's shutdown)
    - `class InProcessExecutor`: `run(call, cancel=None)` returns the stopped outcome without running the
      tool when `cancel` is already set, and otherwise `execute_call(call)`; `cancel()` and `close()` do nothing
    - `CRASH_HINT = "this is a bug in badshop; other steps are unaffected"`; a crash's message is `f"the tool crashed ({type(e).__name__}: {e})"`
    - `STOPPED = "stopped by the user"`: a stopped call's `error_message`, whichever executor stopped it
      (Task 10's `WorkerExecutor` imports it)

Design notes (read before implementing):
- **The policy reads the host the way urllib connects, and the way urlsplit reads it, and checks
  both.** A policy built on `urlsplit(url).hostname` alone, which treats "does not resolve" as a pass, is
  bypassable. urllib percent-decodes the host (`Request.host`), so for `http://%31%32%37.0.0.1:PORT/`
  urlsplit's host `%31%32%37.0.0.1` fails to resolve, yet urllib connects to 127.0.0.1.
  `test_a_percent_encoded_local_host_is_refused` proves the connection against a live local server.
  urlsplit's reading is checked too, so `http://x.org@127.0.0.1/` is refused whichever parser a
  future urllib follows.
- **What counts as local:** every resolved address is checked, and one non-public address refuses the
  URL. Refused addresses: private, loopback, link-local, reserved, multicast, unspecified,
  IPv6 site-local, and anything `ipaddress` does not call `is_global`. The last covers 100.64/10,
  the shared CGNAT space that Tailscale also uses. IPv4-mapped (`::ffff:a.b.c.d`) and NAT64
  (`64:ff9b::a.b.c.d`) addresses are judged by the IPv4 address inside them. Python calls both
  `224.0.0.1` and `fec0::1` `is_global`, so they need the explicit checks. The error never shows the
  resolved address, because that would give a model a DNS oracle for internal names.
- **Trusted links:** only a link the user typed passes, and only on its first hop, as an exact URL match.
  A redirect from it is a new URL, and so is an og:image the typed page points to. Both are checked,
  as carry-forward SEC-S2 requires. `ToolCall` has no actor field. The session (Task 7) builds each
  call with `trusted_urls=netpolicy.typed_urls(step.tool, step.params, step.actor)`, and it has
  already run `runner.validate` with the actor. `execute_call` re-validates the stored JSON params with
  the default `"user"` actor, so an approved user-only field (fetch's `clipboard`) still runs.
- **`URL_POLICY` is process-wide.** One tool call runs at a time per process: the server's tool lock, or
  the worker's single child. Asset downloads made inside a tool (`cached()` for fonts, YuNet and rembg)
  are checked too. Their URLs are public, so they pass. A test that serves an asset from a 127.0.0.1
  server and runs the tool through `execute_call` must pass `guard_network=False`.
- **`BytesStore.load` decodes with `formats=IMPORT_FORMATS, max_pixels=MAX_IMPORT_PIXELS`.** An
  artifact in a hostile `.badshop` can carry a valid hash and still be EPS (Pillow would run
  Ghostscript) or a pixel bomb. Every decode failure becomes an `EngineError`, as in Task 5's `_decode`:
  hostile bytes make Pillow raise `ValueError` or `SyntaxError` as well as `OSError` (a PNG whose IHDR
  chunk is too short is a `ValueError`), and a bad input is not a crash. Pillow's
  `cannot identify image file <_io.BytesIO object at 0x...>` tells the reader nothing, so it is left out
  of the message.
- **Outputs keep their name hints raw** (`"{stem}_work.png"`, `"final:{stem}"`), because Task 7's
  `label_for(record, stem, tool)` makes the label. `ToolCall.stem` is still passed to
  `runner.execute`, which would otherwise build a 64-hex stem from the artifact id through `_stem`.
- **A failed call keeps nothing.** When the second output fails to encode, the first is dropped too,
  and the outcome has `outputs == []` and `lines == []`.
- **Tool data is strict JSON (ruling R4).** `json.dumps` writes a non-finite float as a bare `NaN`,
  `Infinity` or `-Infinity`, and `json.loads` reads those back as floats, so the round trip alone keeps
  them. JavaScript's `JSON.parse` refuses all three. A tool's data travels on into steps, events and
  JSON-RPC replies, and Task 12 frames its replies with plain `json.dumps`. `json_safe` therefore reads
  the three constants back as None (`parse_constant`), once, at the boundary, so the JSON-RPC layer never
  sends a value a JavaScript client can't parse. A numpy float is a `float` subclass and is caught the same
  way. The string `"NaN"` stays a string.
- **The worker pickles `ToolCall` and `ToolOutcome` (Task 10)**, so both hold only plain data.
- **A call carries its own stop signal, not just the executor's `cancel()`.** Task 11's Stop can land
  after a step's thread has been dispatched but before the executor's `run()` begins (the session is still
  naming the outputs, announcing `step.started`, or waiting for the server's lock). An executor-wide
  `cancel()` can't reach that call: Task 10's `WorkerExecutor.run` starts each call with its flag cleared,
  so a cancel meant for an idle worker never stops a later call. So `run` takes the call's own
  `threading.Event`: already set when the call's turn comes, the tool never runs and the outcome is
  `STOPPED`; set while it runs, the worker kills it. `InProcessExecutor` can't stop a tool once it has
  begun, but honours an event that was set first (`test_a_call_stopped_before_it_begins_never_runs`).
  `threading.Event` is not picklable, and does not need to be: it stays in the core, beside the call.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_execution.py`:
```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_execution.py -q`
Expected: a collection error, `ImportError: cannot import name 'netpolicy' from 'badshop.session'`.

- [ ] **Step 3: Implement the private-address policy**

`core/src/badshop/session/netpolicy.py`:
```python
"""Where tools may download from (carry-forward SEC-S2). A page, a search API, a redirect or a model
chooses most of the links a tool follows, so every hop must lead to a public internet address: never
this computer or the local network, or `fetch` becomes a way to read the user's router, NAS or cloud
metadata, and its errors a LAN scanner. Only the link the user typed is let through, on its first hop.

Resolve-then-connect is best effort against DNS rebinding (the name could resolve differently a moment
later, when urllib connects)."""

import http.client
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial

from badshop.engine import assets
from badshop.engine.errors import EngineError
from badshop.tools.runner import is_trusted

LOCAL_HINT = ("badshop only downloads from public internet addresses; to use a picture from this computer "
              "or your own network, save it and import the file")
WEB_LINK = re.compile(r"https?://")  # what makes fetch treat its query as a link (sources.fetch)
NAT64 = ipaddress.IPv6Network("64:ff9b::/96")  # 64:ff9b::a.b.c.d reaches IPv4 a.b.c.d through a translator


def _hosts(url: str) -> list[str]:
    """Every host `url` can mean: the one urllib connects to (Request.host, then HTTPConnection's port
    split) and urlsplit's reading. They differ: urllib percent-decodes the host, so
    `http://%31%32%37.0.0.1/` connects to 127.0.0.1 while urlsplit reads "%31%32%37.0.0.1", which no
    resolver knows; urlsplit drops a `user@` that urllib keeps. Checking both leaves no gap between the
    parsers. Empty when neither finds a host (file:, data:, "http:///x")."""
    hosts = set()
    try:
        netloc = urllib.request.Request(url).host
        if netloc:
            hosts.add(http.client.HTTPConnection(netloc).host)  # no socket until connect()
    except (ValueError, http.client.InvalidURL):  # urllib refuses the link the same way
        pass
    try:
        hosts.add(urllib.parse.urlsplit(url).hostname or "")
    except ValueError:  # an unclosed IPv6 bracket
        pass
    return sorted(h for h in hosts if h)  # not lowercased: an IPv6 zone (fe80::1%ETH0) is case-sensitive


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:  # ::ffff:127.0.0.1 is 127.0.0.1 on a dual-stack socket
        ip = ip.ipv4_mapped
    elif ip.version == 6 and ip in NAT64:
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF)
    local = (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
             or ip.is_unspecified or (ip.version == 6 and ip.is_site_local))
    return ip.is_global and not local  # is_global also rules out shared space 100.64/10 (CGNAT, Tailscale)


def refuse_private(url: str, trusted: frozenset[str] = frozenset()) -> None:
    """Raise EngineError when `url` leads to this computer or a non-public network: any address either
    reading of its host resolves to that is private, loopback, link-local, reserved, multicast or
    unspecified. A URL in `trusted` (the user typed it) passes; a redirect from it is a new URL and is
    checked. A host that doesn't resolve passes too: the request itself fails the same way."""
    if url in trusted:
        return
    for host in _hosts(url):
        try:
            found = socket.getaddrinfo(host, None, 0, socket.SOCK_STREAM)  # as socket.create_connection asks
        except (OSError, UnicodeError):  # gaierror is an OSError; a label over 63 characters, a UnicodeError
            continue
        for *_, sockaddr in found:
            try:
                public = _public(ipaddress.ip_address(sockaddr[0]))
            except ValueError:  # an address this module can't read is not known to be public
                public = False
            if not public:  # the resolved address stays out of the message: it would answer DNS for a model
                raise EngineError(f"refused {url[:60]}: it points into this computer or the local network",
                                  hint=LOCAL_HINT)


def policy_for(trusted: frozenset[str] = frozenset()) -> Callable[[str], None]:
    """refuse_private with `trusted` bound: the shape assets.URL_POLICY takes."""
    return partial(refuse_private, trusted=frozenset(trusted))


@contextmanager
def guarded(trusted: frozenset[str] = frozenset()) -> Iterator[None]:
    """Install the policy as assets.URL_POLICY for the block, so every download, redirect hop and asset
    fetch is checked, then put back whatever was there. URL_POLICY is process-wide: one tool call runs
    at a time in a process (the session's lock, or the worker's single child)."""
    previous = assets.URL_POLICY
    assets.URL_POLICY = policy_for(trusted)
    try:
        yield
    finally:
        assets.URL_POLICY = previous


def typed_urls(tool: str, params: dict, actor: str) -> frozenset[str]:
    """The links the user typed: a trusted actor's fetch whose query is a web link. Everything else (a
    model's query, og:image, search and API results, redirects, a link found on the clipboard) is
    checked. The session builds each ToolCall with `trusted_urls=typed_urls(step.tool, step.params,
    step.actor)`."""
    query = params.get("query")
    if tool == "fetch" and is_trusted(actor) and isinstance(query, str) and WEB_LINK.match(query):
        return frozenset({query})
    return frozenset()
```

- [ ] **Step 4: Implement the tool-call boundary**

`core/src/badshop/session/execution.py`:
```python
"""The tool-call boundary. A ToolCall carries everything one tool run needs (validated JSON params and
the bytes of every input artifact); a ToolOutcome carries everything it made. Both are plain picklable
data, so a call runs the same in this process or in a worker process (session/worker.py)."""

import hashlib
import json
import threading
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError

import badshop
from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.session import netpolicy
from badshop.session.artifacts import IMPORT_FORMATS, MAX_IMPORT_PIXELS
from badshop.tools import runner

CRASH_HINT = "this is a bug in badshop; other steps are unaffected"
STOPPED = "stopped by the user"  # a stopped call's error_message, whichever executor stopped it


@dataclass(frozen=True)
class ToolCall:
    tool: str
    params: dict  # JSON-safe and already validated (with the proposing actor); image refs are full ids
    inputs: dict[str, bytes]  # every artifact id the params reference -> its bytes
    stem: str  # the label stem outputs are named from (the first input's label), for runner.execute
    trusted_urls: frozenset[str] = frozenset()  # links the user typed (netpolicy.typed_urls)
    guard_network: bool = True  # run under netpolicy.guarded(trusted_urls)


@dataclass
class OutputRecord:
    key: str  # "work", "cutout", "1", "sheet"...
    data: bytes  # Output.encode(): exactly the artifact's bytes
    name_hint: str  # as the tool gave it ("{stem}_work.png", "final:{stem}"); the session makes the label
    caption: str = ""


@dataclass
class ToolOutcome:
    ok: bool
    outputs: list[OutputRecord] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)  # JSON-safe
    error_message: str | None = None
    error_hint: str | None = None
    crashed: bool = False  # a bug (not an EngineError): the session reports it the same way


class BytesStore:
    """A Store over one call's input bytes: load() decodes a fresh image each time (the web and import
    formats only, so a hostile project file can't pick Pillow's EPS decoder, which runs Ghostscript),
    put() keeps each output encoded, and export() is refused: only the session writes files."""

    def __init__(self, inputs: dict[str, bytes]):
        self.inputs = inputs
        self.outputs: list[OutputRecord] = []

    def load(self, ref: str) -> Image.Image:
        if ref not in self.inputs:
            raise EngineError(f"no such artifact: {ref}",
                              hint="use an artifact id from a tool result, like a3f9c1d2")
        try:
            return load_image(self.inputs[ref], formats=IMPORT_FORMATS, max_pixels=MAX_IMPORT_PIXELS)
        except Exception as e:  # hostile bytes make a decoder raise almost anything (ValueError, SyntaxError...)
            detail = "" if isinstance(e, UnidentifiedImageError) else f" ({e})"  # "cannot identify" names a BytesIO
            raise EngineError(f"artifact {ref[:8]} can't be read as an image{detail}",
                              hint="import the picture again") from None

    def put(self, output: Output, stem: str) -> str:
        self.outputs.append(OutputRecord(output.key, output.encode(), output.name_hint, output.caption))
        return f"out:{len(self.outputs) - 1}"

    def export(self, ref: str, name: str | None) -> str:
        raise EngineError("export runs in the session",
                          hint="tools that write files (writes_files) run in the session, not in a ToolCall")


def json_safe(data: dict) -> dict:
    """A tool's data as strict JSON: tuples become lists, values JSON has no type for (a Path) become
    their str(), and non-finite floats (NaN, inf, -inf, numpy's too) become None. json.dumps writes those
    floats as bare NaN/Infinity, which JavaScript's JSON.parse refuses; parse_constant is what json.loads
    calls for exactly those three tokens, never for a quoted "NaN"."""
    return json.loads(json.dumps(data, default=str), parse_constant=lambda _: None)


def execute_call(call: ToolCall) -> ToolOutcome:
    """Validate and run one call. An EngineError is a failed step the user or the model can act on; any
    other exception is a crash, reported as a clean message (never a traceback). A failed call keeps
    nothing it made."""
    store = BytesStore(call.inputs)
    try:
        params = runner.validate(call.tool, call.params)  # as "user": the session already checked the actor
        with netpolicy.guarded(call.trusted_urls) if call.guard_network else nullcontext():
            run = runner.execute(call.tool, params, store, stem=call.stem)
        data = json_safe(run.result.data)
        return ToolOutcome(ok=True, outputs=store.outputs, lines=list(run.result.lines), data=data)
    except EngineError as e:
        return ToolOutcome(ok=False, error_message=e.message, error_hint=e.hint)
    except Exception as e:
        return ToolOutcome(ok=False, crashed=True, error_hint=CRASH_HINT,
                           error_message=f"the tool crashed ({type(e).__name__}: {e})")


def cache_key(tool: str, params: dict) -> str:
    """Identifies one execution: the engine version, the tool and its stored params. Image refs in
    stored params are full artifact ids (content hashes), so the key covers the input bytes too."""
    blob = json.dumps({"engine": badshop.__version__, "tool": tool, "params": params},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


@runtime_checkable
class Executor(Protocol):
    """Runs ToolCalls: InProcessExecutor here, WorkerExecutor (session/worker.py) in a child process.

    `cancel` is one call's own stop signal (the agent's Stop hands one to each step it runs). Set before
    the call begins, the tool never runs; set while it runs, an executor that can stop a tool stops it.
    Either way the outcome is `ok=False` with `error_message=STOPPED`, not a crash. `cancel()` stops the
    call running at that moment, for callers with no event of their own (the server's shutdown); it
    can't reach a call that hasn't begun."""

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class InProcessExecutor:
    """Runs each call in this process, for tests and embedding: no time or memory limit, and once a tool
    has begun neither its cancel event nor cancel() can stop it (WorkerExecutor can). A call whose event
    is already set never runs."""

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome:
        if cancel is not None and cancel.is_set():  # stopped before it began
            return ToolOutcome(ok=False, error_message=STOPPED)
        return execute_call(call)

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        pass
```

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_execution.py -q`
Expected: `59 passed` in about a second, offline. The tests use numeric hosts, a monkeypatched resolver
and a 127.0.0.1 server; `localhost` resolves from the hosts file.

Then run the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1050 passed, 1 deselected` (Task 5's 991 plus these 59; the deselected one is the `network` test), and
ruff prints `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add core/src/badshop/session/netpolicy.py core/src/badshop/session/execution.py core/tests/test_execution.py
git commit -m "feat(session): tool-call boundary and private-address URL policy

ToolCall/ToolOutcome/BytesStore/execute_call run one validated call on
artifact bytes and turn any non-EngineError into a clean crashed outcome;
json_safe makes tool data strict JSON (NaN and infinities become null);
Executor.run takes the call's own cancel event, so a stop that lands
before the call begins is never lost;
netpolicy refuses private, loopback, link-local, reserved, multicast and
unspecified addresses on every hop, reading hosts the way urllib does.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Session core: propose, run, reject, export, labels, result text, events

**Files:**
- Create: `core/src/badshop/session/session.py`
- Test: `core/tests/test_session.py`

**Interfaces:**
- Consumes:
  - Plan 1: `engine.errors.EngineError(message, hint)`; `engine.result.Output` (`key`, `name_hint`, `caption`, `encode()`); `engine.types.FileName`; `engine.sources.TWEMOJI_URL` (test only); `tools.registry.REGISTRY`, `registry.get(name) -> ToolSpec`, `registry.image_fields(params_cls) -> dict[str, bool]` (field order = model field order); `ToolSpec.params`.
  - Task 2: `ToolSpec.writes_files` (True for `export` only); `runner.validate(name: str, raw: dict, actor: str = "user") -> Params`; `runner.execute(name, params, store, stem: str | None = None) -> ToolRun`; `runner.explain(e: ValidationError) -> str`; `FetchParams.clipboard` is user-only.
  - Task 5: `files.final_path(final_dir: Path, stem: str, ext: str) -> Path`, `files.default_output_dir() -> Path`; `session.models.SessionData`, `Step`, `StepError`, `Message`, `Part`, `Source`, `ArtifactMeta` (property `ext`); `session.artifacts.ArtifactStore()` (no arguments: an empty store) with `meta` (mutated in place and never rebound, because the session shares that dict as `data.artifacts`), `add(data, label, *, produced_by=None, source=None, original_id=None) -> ArtifactMeta` (an existing id returns the stored meta unchanged), `data(id)`, `image(id)`, `resolve(ref)`, `ids()`, `in`, and `import_image(data: bytes, label: str, source: Source | None = None, *, produced_by: str | None = None) -> tuple[ArtifactMeta, ArtifactMeta]` (working copy, original; `produced_by` goes on every artifact the call stores: the original and the working copy, or the one artifact that is both halves when a small upright PNG is its own working copy; `None`, the default, for the user's own imports); `describe(meta) -> str`, `short(id) -> str`. This task uses `import_image` as Task 5 writes it and does not change `artifacts.py`.
  - Task 6: `session.execution.ToolCall`, `OutputRecord`, `ToolOutcome`, `cache_key(tool: str, params: dict) -> str`, `json_safe(data: dict) -> dict` (ruling R4's coercion: tuples to lists, `str()` for other types, NaN and infinities to None), `Executor` (`run(call, cancel: threading.Event | None = None) -> ToolOutcome`: a call whose `cancel` is set before it begins never runs, and a stopped call's outcome is `ok=False` with `error_message=STOPPED`), `InProcessExecutor`, `CRASH_HINT`, `STOPPED = "stopped by the user"`; `session.netpolicy.typed_urls(tool: str, params: dict, actor: str) -> frozenset[str]` (the one trusted-URL rule: a trusted actor's `fetch` whose query is a web link; empty for everything else).
- Produces:
  - `core/src/badshop/session/session.py`:
    - `Emit = Callable[[str, dict], None]`; `RUNNABLE = ("proposed", "approved")`. `CRASH_HINT` and `json_safe` are Task 6's (`execution.CRASH_HINT`, `execution.json_safe`), imported and not redefined.
    - `label_for(record: OutputRecord, stem: str, tool: str) -> str`.
    - `result_text(step: Step, artifacts: ArtifactStore, outcome: ToolOutcome | None = None) -> str` (keys, captions and the tool's lines come from `outcome`; the text is computed once per run and stored as `step.result_text`, which is what the agent loop and the server read).
    - `class Session`: `__init__(self, data: SessionData, artifacts: ArtifactStore, *, executor: Executor | None = None, emit: Emit | None = None, output_dir: Path | None = None, on_change: Callable[[], None] | None = None)`; `@classmethod new(cls, name: str = "Untitled", **kw) -> Session`; attributes `data`, `artifacts`, `executor` (default `InProcessExecutor()`), `emit`, `output_dir` (default `files.default_output_dir()`), `on_change`, `changes: list[str]`; `data.artifacts is artifacts.meta`.
    - Methods: `import_image(data: bytes, label: str, source: Source | None = None) -> ArtifactMeta` (the working copy; appends the change note `"the user added image a3f9c1d2 (lincoln_work)"` unless that same line is already waiting in `changes`, so the agent hears about a picture the user adds without attaching it to a message, spec 5.3; pictures a step brings in go through `ArtifactStore.import_image` in `_store_outputs` and write no such note); `add_message(role: str, parts: list[Part], step_ids: Sequence[str] = ()) -> Message`; `propose(tool: str, raw: dict, actor: str, reason: str | None = None) -> Step`; `run(step_id: str, raw: dict | None = None, *, cancel: threading.Event | None = None) -> Step` (`cancel` is the caller's stop signal for this one run, Task 11's Stop: it goes to the executor with the call, and a stopped run is a step with status `"error"` and error message `STOPPED`, like any failed step); `run_tool(tool: str, raw: dict, actor: str, reason: str | None = None) -> Step`; `reject(step_id: str, note: str | None = None) -> Step`; `export(artifact_id: str, name: str | None = None) -> Path` (never overwrites and never loops: a broken link holding the chosen name is `EngineError("can't write <name>: a broken link with that name is in <folder>")`, and 100 names taken by other programs in a row is `EngineError("no free file name for <name> in <folder>")`); `step(step_id: str) -> Step`; `last_output() -> str | None`; `summary() -> str`; `take_changes() -> list[str]`.
    - Helpers Task 8 reuses from the same file: `_image_refs(step: Step) -> list[str]` (module function: the ids a step reads, in field order), `Session._resolved(params: Params) -> dict` (JSON params with full ids), `Session._stem(step: Step) -> str`, `Session._execute(step: Step, cancel: threading.Event | None = None) -> Step` (runs any step on its stored params: status running, then done or error, events, `on_change`; it never raises for a tool failure and writes no change note; `cancel` goes to the executor, and replays pass none), `Session._emit(event: str, step: Step, outputs: Sequence[str] = ())` (the event payload above), `Session._changed()` (calls `on_change`) and `Session._named(artifact_id: str) -> str` (`"a3f9c1d2 (lincoln_paste)"`).
    - The three places Task 8 edits in this file, which Step 3 writes exactly as Task 8 quotes them: the first standard-library imports (`import json`, `import re`, `import threading`, `import time`); the end of `_image_refs`, the module function just above `label_for`, whose last two lines are `refs.extend(value if is_list else [value])` and `return refs`, indented as in Step 3 (Task 8 inserts its `_BUSY` table and three module helpers right after them); and `take_changes`, the last method of `Session`. The file has no `_typed_urls` and no other URL helper: `_execute` calls Task 6's `netpolicy.typed_urls` itself.
    - Events, all with the payload `{"step": step.model_dump(mode="json"), "artifacts": [meta.model_dump(mode="json") for each of the step's outputs]}`: `step.proposed` (propose), `step.started` (run), `step.finished` (done or rejected), `step.failed` (error).
    - Ids: steps `"s1"`, `"s2"`... and messages `"m1"`, `"m2"`..., each one past the highest number that a step, a message, a message's `step_ids` or an artifact's `produced_by` still names, so an id never comes back after Task 8's `delete_last`. `Step.index` is the step's 1-based position.

- [ ] **Step 1: Write the failing tests**

`ScriptedExecutor` stands in for the worker: it records each `ToolCall` and answers with canned outcomes, so provenance, trusted URLs and crashes are tested offline and in milliseconds. Everything else runs the real tools in-process (`prep`, `filter`, `view`, `cutout` without the background remover, `paste`, `deepfry`, `save`, `export`), none of which downloads anything. `test_a_small_fetched_png_is_one_artifact_that_still_records_its_step` covers the branch of Task 5's `import_image` that stores one artifact as both halves (a small transparent PNG, which is what `emoji` hands back), as the session reaches it. `test_the_agent_hears_about_pictures_the_user_adds` covers the import change note (spec 5.3). `test_export_never_loops_on_a_name_it_cannot_take` covers a broken link in the output folder, a name another program takes between `final_path` and the write, and names that keep being taken. `test_a_run_stopped_before_its_tool_begins_is_a_failed_step` pins that `run` hands the caller's cancel event to the executor with the call (`ScriptedExecutor.stops` records each call's event, or None), that a stop set before the tool begins leaves the tool unrun and the step failed with `STOPPED`, and that `export`, which runs in the session, is stopped the same way. `test_a_tool_that_writes_files_hands_back_strict_json_too` registers a throwaway tool with `writes_files` (monkeypatch removes it again) to pin that the session's own in-process path applies Task 6's `json_safe` to a tool's data, as `execute_call` does (ruling R4).

`core/tests/test_session.py`:
```python
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
    assert dumped["schema"] == 1 and dumped["name"] == "Untitled"


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_session.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'badshop.session.session'`.

- [ ] **Step 3: Implement the session core**

`core/src/badshop/session/session.py`:
```python
"""A session: artifacts, steps and chat, and the one place every tool call goes through (spec 5, 5.3).

The user, the in-app agent and CLI agents all propose a step here and run it here, so the timeline,
approvals, edits and replay work the same for every caller. Engine rules still hold: nothing here prints,
and every failure a caller can act on is an EngineError."""

import json
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter, ValidationError

from badshop import files
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.engine.types import FileName
from badshop.session import netpolicy
from badshop.session.artifacts import ArtifactStore, describe, short
from badshop.session.execution import (CRASH_HINT, STOPPED, Executor, InProcessExecutor, OutputRecord,
                                       ToolCall, ToolOutcome, cache_key, json_safe)
from badshop.session.models import ArtifactMeta, Message, Part, SessionData, Source, Step, StepError
from badshop.tools import registry, runner

Emit = Callable[[str, dict], None]

RUNNABLE = ("proposed", "approved")  # a step waiting to run; anything else has run, failed or been rejected
_MARKS = {"done": "✓", "error": "✗"}  # summary() writes every other status as its name
_ROOT_SUFFIX = re.compile(r"_(work|result)$")  # the CLI's clean_stem: lincoln_work names lincoln
_FILE_NAME = TypeAdapter(FileName)
_EXPORT_TRIES = 100  # names export tries before giving up, when other programs keep taking them first


def _crashed(e: Exception) -> ToolOutcome:
    return ToolOutcome(False, error_message=f"the tool crashed ({type(e).__name__}: {e})",
                       error_hint=CRASH_HINT, crashed=True)


def _image_refs(step: Step) -> list[str]:
    """The artifact ids a step reads, in field order (paste: base, then piece). A tool this version
    doesn't have reads nothing here; running it is the executor's clean "unknown tool" error."""
    spec = registry.REGISTRY.get(step.tool)
    refs: list[str] = []
    for name, is_list in (registry.image_fields(spec.params) if spec else {}).items():
        value = step.params.get(name)
        if value is not None:
            refs.extend(value if is_list else [value])
    return refs


def label_for(record: OutputRecord, stem: str, tool: str) -> str:
    """An output's artifact label, from its name hint: `final:{stem}_deepfried` -> lincoln_deepfried,
    `fetch/lincoln_1.jpg` -> lincoln_1, `{stem}_work.png` -> lincoln_work. The generic `result.png`
    becomes lincoln_paste, or just paste when the step has no image input."""
    hint = record.name_hint
    if hint.startswith("final:"):  # a finished file's name has no extension: "my.meme" stays whole
        name = hint.removeprefix("final:").replace("{stem}", stem)
    else:
        name = PurePosixPath(hint.replace("{stem}", stem)).stem
    if name == "result":
        name = f"{stem}_{tool}" if stem else tool
    return name.strip("_") or tool


def result_text(step: Step, artifacts: ArtifactStore, outcome: ToolOutcome | None = None) -> str:
    """What the caller reads back (the agent's tool result, the step drawer): one line per output,
    `key: a3f9c1d2 (label, WxH) caption`, then the tool's own lines; `error:` and `hint:` for a failed
    step. Keys, captions and lines come from the run's outcome; without one, outputs are numbered."""
    if step.error is not None:
        return f"error: {step.error.message}" + (f"\nhint: {step.error.hint}" if step.error.hint else "")
    records = outcome.outputs if outcome is not None else []
    lines = []
    for i, id in enumerate(step.outputs):
        key, caption = (records[i].key, records[i].caption) if i < len(records) else (str(i + 1), "")
        lines.append(f"{key}: {describe(artifacts.meta[id])}" + (f" {caption}" if caption else ""))
    if outcome is not None:
        lines += outcome.lines
    return "\n".join(lines) or "done"


class _SessionStore:
    """The Store for tools that write files (export): they run in the session's process, because the
    output folder is the session's. Outputs are collected exactly as the worker collects them."""

    def __init__(self, session: "Session"):
        self.session = session
        self.records: list[OutputRecord] = []

    def load(self, ref: str):
        artifacts = self.session.artifacts
        return artifacts.image(artifacts.resolve(ref))

    def put(self, output: Output, stem: str) -> str:
        self.records.append(OutputRecord(output.key, output.encode(), output.name_hint, output.caption))
        return f"out:{len(self.records) - 1}"

    def export(self, ref: str, name: str | None) -> str:
        return str(self.session.export(ref, name))


class Session:
    """One open session. Not thread-safe: the server runs one call at a time (spec 5.6)."""

    def __init__(self, data: SessionData, artifacts: ArtifactStore, *, executor: Executor | None = None,
                 emit: Emit | None = None, output_dir: Path | None = None,
                 on_change: Callable[[], None] | None = None):
        self.data, self.artifacts = data, artifacts
        # One dict: a snapshot or a project file of `data` always lists every artifact the store holds.
        self.data.artifacts = artifacts.meta
        self.executor: Executor = executor if executor is not None else InProcessExecutor()
        self.emit: Emit = emit or (lambda event, payload: None)
        self.output_dir = output_dir if output_dir is not None else files.default_output_dir()
        self.on_change = on_change or (lambda: None)
        self.changes: list[str] = []  # what the user did that the agent hasn't heard about yet

    @classmethod
    def new(cls, name: str = "Untitled", **kw) -> "Session":
        data = SessionData(id=uuid.uuid4().hex, name=name, created_at=time.time())
        return cls(data, ArtifactStore(), **kw)

    # ids, lookups, events

    def _next_id(self, prefix: str) -> str:
        """s1, s2... and m1, m2...: one past the highest number anything still names, so an id never
        comes back while an artifact or a message points at it (the last step can be deleted)."""
        names = [s.id for s in self.data.steps] + [m.id for m in self.data.messages]
        names += [sid for m in self.data.messages for sid in m.step_ids]
        names += [a.produced_by for a in self.artifacts.meta.values() if a.produced_by]
        numbers = [int(n[len(prefix):]) for n in names if n.startswith(prefix) and n[len(prefix):].isdigit()]
        return f"{prefix}{max(numbers, default=0) + 1}"

    def step(self, step_id: str) -> Step:
        for s in self.data.steps:
            if s.id == step_id:
                return s
        raise EngineError(f"no such step: {step_id}", hint="use a step id from the timeline, like s3")

    def _emit(self, event: str, step: Step, outputs: Sequence[str] = ()) -> None:
        metas = [self.artifacts.meta[i].model_dump(mode="json") for i in dict.fromkeys(outputs)]
        self.emit(event, {"step": step.model_dump(mode="json"), "artifacts": metas})

    def _changed(self) -> None:
        self.on_change()

    def _resolved(self, params) -> dict:
        """Validated params as JSON, each image ref (an id or a unique prefix) replaced by the full id."""
        dumped = params.model_dump(mode="json")
        for name, is_list in registry.image_fields(type(params)).items():
            value = dumped.get(name)
            if value is not None:
                resolve = self.artifacts.resolve
                dumped[name] = [resolve(v) for v in value] if is_list else resolve(value)
        return dumped

    def _stem(self, step: Step) -> str:
        """What a step's outputs are named after: its first image input, traced back through the steps
        that made it to the picture it started from, so edits on lincoln give lincoln_text and then
        lincoln_deepfried, not lincoln_text_deepfried."""
        makers = {s.id: s for s in self.data.steps}
        refs, label, seen = _image_refs(step), "", set()
        while refs and refs[0] in self.artifacts and refs[0] not in seen:
            seen.add(refs[0])
            meta = self.artifacts.meta[refs[0]]
            label = meta.label
            maker = makers.get(meta.produced_by) if meta.produced_by else None
            refs = _image_refs(maker) if maker is not None else []
        return _ROOT_SUFFIX.sub("", label)

    # user input

    def import_image(self, data: bytes, label: str, source: Source | None = None) -> ArtifactMeta:
        """A dropped, pasted or opened picture: stored as a working copy (returned) plus the original.
        The agent hears about it in its next system note even when no message carries it (spec 5.3);
        the same picture added twice before then is one line."""
        working, _original = self.artifacts.import_image(data, label, source)
        note = f"the user added image {self._named(working.id)}"
        if note not in self.changes:
            self.changes.append(note)
        self._changed()
        return working

    def add_message(self, role: str, parts: list[Part], step_ids: Sequence[str] = ()) -> Message:
        content = []
        for part in parts:
            if part.type == "image":
                if not part.artifact_id:
                    raise EngineError("an image part needs an artifact id")
                part = part.model_copy(update={"artifact_id": self.artifacts.resolve(part.artifact_id)})
            content.append(part)
        for sid in step_ids:
            self.step(sid)  # an unknown step id is this clean error
        message = Message(id=self._next_id("m"), role=role, content=content, step_ids=list(step_ids))
        self.data.messages.append(message)
        self._changed()
        return message

    # the step lifecycle: propose -> run (done | error) or reject

    def propose(self, tool: str, raw: dict, actor: str, reason: str | None = None) -> Step:
        """Validate a call for `actor` and add it as a proposed step. Image refs must name artifacts of
        this session (never paths, whoever asks); they are stored as full ids."""
        params = self._resolved(runner.validate(tool, raw, actor))
        step = Step(id=self._next_id("s"), index=len(self.data.steps) + 1, tool=tool, params=params,
                    actor=actor, status="proposed", reason=reason)
        self.data.steps.append(step)
        self._emit("step.proposed", step)
        self._changed()
        return step

    def run(self, step_id: str, raw: dict | None = None, *, cancel: threading.Event | None = None) -> Step:
        """Run a proposed step, with the user's edited params when given (validated as the user's).
        `cancel` is the caller's stop signal for this one run (the agent's Stop): it goes to the executor
        with the call, and a stopped run is a failed step with the executor's "stopped by the user"."""
        step = self.step(step_id)
        if step.status not in RUNNABLE:
            raise EngineError(f"step {step.id} is {step.status}, so it can't run",
                              hint="only a proposed step runs; edit a finished step and replay it instead")
        if raw is not None:
            params = self._resolved(runner.validate(step.tool, raw, "user"))
            if params != step.params:
                step.params, step.edited = params, True
        self._execute(step, cancel)
        if step.actor == "user":
            self.changes.append(self._change_note(step))
        return step

    def run_tool(self, tool: str, raw: dict, actor: str, reason: str | None = None) -> Step:
        return self.run(self.propose(tool, raw, actor, reason).id)

    def reject(self, step_id: str, note: str | None = None) -> Step:
        step = self.step(step_id)
        if step.status not in RUNNABLE:
            raise EngineError(f"step {step.id} is {step.status}, so it can't be rejected",
                              hint="only a step waiting for approval can be rejected")
        step.status, step.finished_at = "rejected", time.time()
        step.result_text = "rejected by user" + (f": {note}" if note else "")
        self._emit("step.finished", step)
        self._changed()
        return step

    def _execute(self, step: Step, cancel: threading.Event | None = None) -> Step:
        """Run a step's tool on its stored params and record the outcome. Never raises for a tool's
        failure: an EngineError, a crash, a killed worker or a stop (`cancel`, set by the caller) is a
        failed step with a clean error."""
        stem = self._stem(step)
        step.status, step.started_at, step.finished_at = "running", time.time(), None
        step.outputs, step.result_text, step.data, step.error = [], "", None, None
        step.cache_key = cache_key(step.tool, step.params)
        self._emit("step.started", step)  # no on_change here: an autosave never holds a running step
        try:
            if registry.get(step.tool).writes_files:
                outcome = self._run_here(step, stem, cancel)
            else:
                inputs = {id: self.artifacts.data(self.artifacts.resolve(id)) for id in _image_refs(step)}
                trusted = netpolicy.typed_urls(step.tool, step.params, step.actor)  # a user's own link
                call = ToolCall(step.tool, step.params, inputs, stem, trusted_urls=trusted,
                                guard_network=True)
                outcome = self.executor.run(call, cancel=cancel)  # the caller's stop goes with its call
            outputs = self._store_outputs(step, outcome, stem) if outcome.ok else []
        except EngineError as e:
            outcome, outputs = ToolOutcome(False, error_message=e.message, error_hint=e.hint), []
        except Exception as e:  # a bug, in the session or a tool: one failed step, the session goes on
            outcome, outputs = _crashed(e), []
        step.finished_at = time.time()
        if outcome.ok:
            step.status, step.outputs = "done", outputs
            step.data = {k: v for k, v in outcome.data.items() if k != "sources"} or None
        else:
            step.status = "error"
            step.error = StepError(message=outcome.error_message or "the tool failed",
                                   hint=outcome.error_hint)
        step.result_text = result_text(step, self.artifacts, outcome)
        self._emit("step.finished" if outcome.ok else "step.failed", step, step.outputs)
        self._changed()
        return step

    def _run_here(self, step: Step, stem: str, cancel: threading.Event | None) -> ToolOutcome:
        if cancel is not None and cancel.is_set():  # stopped before it began, as an executor answers
            return ToolOutcome(False, error_message=STOPPED)
        store = _SessionStore(self)
        params = registry.get(step.tool).params.model_validate(step.params)
        try:
            run = runner.execute(step.tool, params, store, stem=stem)
        except EngineError as e:
            return ToolOutcome(False, error_message=e.message, error_hint=e.hint)
        return ToolOutcome(True, store.records, list(run.result.lines), json_safe(run.result.data))

    def _store_outputs(self, step: Step, outcome: ToolOutcome, stem: str) -> list[str]:
        """Outputs become artifacts. A picture from outside (its `sources` entry is a dict) enters as a
        <=1000 px working copy with its original kept beside it (spec 5.3); the rest are stored as they
        are. Identical bytes are one artifact, which keeps the first step that made it."""
        sources = outcome.data.get("sources") or []
        ids = []
        for i, record in enumerate(outcome.outputs):
            label = label_for(record, stem, step.tool)
            source = sources[i] if i < len(sources) else None
            if isinstance(source, dict):  # working copy and original both record this step
                where = Source.model_validate(source)
                meta, _original = self.artifacts.import_image(record.data, label, where, produced_by=step.id)
            else:
                meta = self.artifacts.add(record.data, label, produced_by=step.id)
            ids.append(meta.id)
        return ids

    def _change_note(self, step: Step) -> str:
        """One line for the agent's next system note about a step the user ran."""
        spec = registry.get(step.tool)
        shown = spec.params.model_validate(step.params).model_dump(mode="json", exclude_defaults=True)
        for name, is_list in registry.image_fields(spec.params).items():
            if shown.get(name) is not None:
                shown[name] = [short(v) for v in shown[name]] if is_list else short(shown[name])
        call = f"{step.tool} {json.dumps(shown, ensure_ascii=False)}"
        if step.error is not None:
            return f"the user ran step {step.index}: {call}, which failed: {step.error.message}"
        made = ", ".join(self._named(i) for i in step.outputs) or "no images"
        return f"the user ran step {step.index}: {call} → {made}"

    # files and summaries

    def export(self, artifact_id: str, name: str | None = None) -> Path:
        """Write an artifact's bytes, unchanged, into the output folder as `name` (or its label) plus
        its format's extension, never overwriting: lincoln.png, lincoln_2.png..."""
        meta = self.artifacts.meta[self.artifacts.resolve(artifact_id)]
        if name is not None:
            try:
                name = _FILE_NAME.validate_python(name)
            except ValidationError as e:
                raise EngineError(f"bad file name {name!r}", hint=runner.explain(e)) from None
        stem, data = name or meta.label, self.artifacts.data(meta.id)
        try:
            for _ in range(_EXPORT_TRIES):
                path = files.final_path(self.output_dir, stem, meta.ext)
                try:
                    with open(path, "xb") as f:  # "x": a file that appeared since final_path looked is kept
                        f.write(data)
                    return path
                except FileExistsError:
                    # Another program took the name since final_path looked: the next try gets the next
                    # name. Not so for a broken link: final_path doesn't see it (it doesn't "exist"), so it
                    # would hand back this name forever, and "x" never replaces it.
                    if path.is_symlink() and not path.exists():
                        raise EngineError(f"can't write {path.name}: a broken link with that name is in "
                                          f"{self.output_dir}",
                                          hint="remove it, or export under another name") from None
        except OSError as e:
            raise EngineError(f"can't write into {self.output_dir} ({e})",
                              hint="check the output folder exists and is writable") from None
        raise EngineError(f"no free file name for {stem}{meta.ext} in {self.output_dir}",
                          hint="another program keeps taking those names; try again, or use another name")

    def _named(self, artifact_id: str) -> str:
        meta = self.artifacts.meta.get(artifact_id)
        return f"{short(artifact_id)} ({meta.label})" if meta else short(artifact_id)

    def last_output(self) -> str | None:
        """The newest finished picture: the last output of the latest done step (tools put the one to
        look at last: fetch's contact sheet, prep's grid)."""
        for step in reversed(self.data.steps):
            if step.status == "done" and step.outputs:
                return step.outputs[-1]
        return None

    def summary(self) -> str:
        """One line per step: `3. cutout by agent:fake ✓ → a3f9c1d2 (trump_cutout)`."""
        lines = []
        for step in self.data.steps:
            line = f"{step.index}. {step.tool} by {step.actor} {_MARKS.get(step.status, step.status)}"
            if step.edited:
                line += " (edited)"
            if step.outputs:
                line += " → " + ", ".join(self._named(i) for i in step.outputs)
            if step.error is not None:
                line += f": {step.error.message}"
            lines.append(line)
        return "\n".join(lines)

    def take_changes(self) -> list[str]:
        changes, self.changes = self.changes, []
        return changes
```

Notes on the design (the reasons behind choices the brief left open):
- **A caller's stop goes with its call.** `run(..., cancel=event)` passes the event to `_execute`, which hands it to `self.executor.run(call, cancel=cancel)`, so Task 11's Stop reaches this one call even when it lands before the executor's `run()` begins (while `_stem`, `cache_key` or `step.started` run, or while the server's lock is still held by someone else); an executor-wide `cancel()` would miss that call and could stop another caller's. A stopped call is an ordinary failed step: status `"error"`, message `STOPPED`, `step.failed`. `_run_here` (export) checks the event before it writes anything, as an executor does. Replays (Task 8) and the user's own runs pass no event.
- **Every tool call goes through `_execute`.** Tools with `writes_files` (`export`) run in this process through `_SessionStore`, whose `export` is `Session.export`, because the output folder belongs to the session. Every other tool goes to `self.executor.run(ToolCall(...))` with `inputs` holding the bytes of every id the step reads. An `EngineError`, an executor that raises, or an output that doesn't store becomes a failed step with a clean `StepError`, never a step left `running`. A crash on the session side uses Task 6's `CRASH_HINT`, so it reads exactly like a crash inside `execute_call`. The in-process path also hands its tool's data through Task 6's `json_safe`, the coercion `execute_call` applies (ruling R4), so a step's `data` is strict JSON whichever way its tool ran; `_SessionStore.put` numbers its refs from 0 like `BytesStore.put`.
- **Pictures from outside enter as working copies (spec 5.3).** An output whose `data["sources"][i]` is a dict is stored with Task 5's `ArtifactStore.import_image(..., produced_by=step.id)`: a working copy of at most 1000 px (what later tools see, and what `step.outputs` lists) plus the tool's full-size output bytes as its original, both credited to the step. A small upright PNG is its own working copy and is stored once, still credited to the step (Task 5 puts `produced_by` on that one artifact too). Fetch's contact sheet (`None`) and every other tool's outputs are stored as they are with `add`. `sources` goes onto the artifacts; the rest of `data` goes onto the step.
- **Identical bytes are one artifact.** `ArtifactStore.add` returns the stored meta for a known id, so the artifact keeps the first `produced_by` and label. A second step that makes the same picture lists the same id in its outputs, and its event carries that meta.
- **Labels name the picture a chain started from.** The stem is the label of the step's first image input, traced back through the steps that produced it to its root, with a trailing `_work` or `_result` removed (the CLI's `clean_stem`). Edits on Lincoln give `lincoln_filter`, `lincoln_paste`, then `lincoln_deepfried`, not `lincoln_filter_paste_deepfried`. The same stem goes into `ToolCall.stem`.
- **URLs.** `ToolCall.trusted_urls` is `netpolicy.typed_urls(step.tool, step.params, step.actor)`, Task 6's single rule: only a user's `fetch` whose query is a web link skips the address check, and only on its first hop. The session keeps no copy of that rule: there is no `_typed_urls` in this file, and the module functions are `_crashed`, `_image_refs`, `label_for` and `result_text`, in that order. A model's query, og:image links, API results and redirects all go through Task 6's private-address policy, and so does an agent step the user edits on approval, which keeps its agent actor. `guard_network` is always True in a session.
- **Export never overwrites and never loops.** `export` writes with `open(path, "xb")`, so a file another program created after `final_path` looked is kept, and on `FileExistsError` it asks `final_path` again for the next free name. A broken symlink is the one name `final_path` can't see (`Path.exists()` is False for it) and `"x"` can't replace, so `final_path` would return it forever. That case is a clean `EngineError` naming the link. After 100 taken names in a row, `export` gives up with "no free file name". This matters in the server: `export` (the RPC method and the agent's `export` tool) runs under the one tool lock, so an endless loop would freeze the core.
- **`result_text`.** A `Step` stores no output keys, captions or tool lines, so they come from the run's `ToolOutcome`. The text is built once per run and stored in `step.result_text`. That field is what the agent loop (the tool message) and the server read. A rejected step's text is `"rejected by user"` or `"rejected by user: <note>"`.
- **`on_change` (the autosave hook)** runs after every settled change: import, message, propose, a run's end, reject. It does not run when a step enters `running`, so an autosave never holds a step that a restore would show stuck in `running`.
- **Change notes.** `run` (not `_execute`) adds one line to `changes` when the step's actor is `"user"`, e.g. `the user ran step 4: text {"image": "a3f9c1d2", "text": "hello"} → b4c5d6e7 (lincoln_text)`. Replays (Task 8) call `_execute` and write their own note. Rejections are not change notes, because the agent already gets them as the tool result.
- **Imports are change notes too (spec 5.3).** `Session.import_image` adds `the user added image a3f9c1d2 (lincoln_work)`, because the user can drop or paste a picture without attaching it to a message, and the agent must still hear of it at its next turn (Task 11's system note). The line is skipped when the very same line is already waiting, so dropping one picture twice before the agent's turn is one line; after `take_changes`, adding it again is news again. A picture a step brings in (`fetch`, `wiki`, `emoji`, `template`) is stored by `_store_outputs` through `ArtifactStore.import_image`, not through `Session.import_image`, so it writes no such note: an agent's step reports it in its tool result, and a user's step in its run note.

- [ ] **Step 4: Run the tests**

Run: `cd core && uv run pytest tests/test_session.py -q`
Expected: `33 passed` in about 3 seconds, offline.

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1083 passed, 1 deselected` (Task 6's 1050 plus these 33; the deselected one is the `network` test; `artifacts.py` and `test_artifacts.py` are Task 5's, unchanged here), and ruff prints `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add core/src/badshop/session/session.py core/tests/test_session.py
git commit -m "feat(session): session core: propose, run, reject, export, labels, result text, events

Fetched pictures enter as working copies credited to the step that
fetched them, a picture the user adds becomes a change note for the
agent, export never loops on a name it cannot take, and run() hands
the caller's cancel event to the executor with the call.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Session edit, replay with remapping and cache, delete last step

**Files:**
- Modify: `core/src/badshop/session/models.py` (one new field on `Step`), `core/src/badshop/session/session.py` (one import, the `_BUSY` table and three module helpers after `_image_refs`, and the `Session` methods after `take_changes`)
- Create: `core/tests/test_replay.py`
- Test: `core/tests/test_replay.py`

**Interfaces:**
- Consumes:
  - Plan 1: `engine.errors.EngineError(message, hint)`; `tools.registry.get(name) -> ToolSpec` (`.params`), `registry.image_fields(params_cls) -> dict[str, bool]` (field -> is a list).
  - Task 2: `runner.validate(name: str, raw: dict, actor: str = "user") -> Params`.
  - Task 5: `session.models.Step` (`id, index, tool, params, actor, status, outputs, result_text, data, error, reason, edited, started_at, finished_at, cache_key`), `StepError`, `Part` (`type`, `text`, `artifact_id`), `Message` (`content`, `step_ids`), `SessionData` (`model_dump(mode="json", by_alias=True)` and `model_validate`; `transcript: list[dict]`, the provider-format history Task 11 writes), `ArtifactMeta` (`produced_by`: the first step that made the bytes, `None` for an import; `original_id`); `session.artifacts.ArtifactStore` (`meta`, `in`, `drop(ids)`, `resolve(ref)`), `short(id) -> str` (the first 8 hex).
  - Task 6: `session.execution.cache_key(tool: str, params: dict) -> str`; `InProcessExecutor` (tests; its `run(call, cancel=None)` takes the call's optional cancel event, which Task 7's `_execute` always passes, so the tests' `Counting` executor takes it and hands it on).
  - Task 7 (`session/session.py`, public): `Session(data, artifacts, *, executor=None, emit=None, output_dir=None, on_change=None)`, `Session.new(name="Untitled", **kw)`; attributes `data`, `artifacts` (`data.artifacts is artifacts.meta`), `emit` (an `Emit`, a no-op when none was given, never None), `changes`; `import_image`, `add_message(role, parts, step_ids=())`, `propose`, `run_tool`, `reject`, `summary()`, `step(step_id) -> Step` (EngineError `no such step` for an unknown id), `take_changes()`. Step ids come from `_next_id`: one past the highest number that a step, a message, a message's `step_ids` or an artifact's `produced_by` names.
  - Task 7 (helpers in the same file): `_image_refs(step: Step) -> list[str]` (module function: the ids a step reads, in field order); `Session._resolved(params: Params) -> dict` (JSON params, image refs as full ids); `Session._execute(step: Step, cancel: threading.Event | None = None) -> Step` (replays pass no `cancel`; runs any step on its stored params whatever its status: outputs cleared, `cache_key = cache_key(step.tool, step.params)`, `step.started` then `step.finished` or `step.failed`, `on_change`; never raises for the tool's failure, a missing input artifact included; writes no change note); `Session._emit(event: str, step: Step, outputs: Sequence[str] = ())` (payload `{"step": ..., "artifacts": [meta of each output]}`); `Session._changed()`; `Session._named(artifact_id) -> str` (`"a3f9c1d2 (lincoln_paste)"`).
- Produces:
  - `models.Step.previous_outputs: list[str] = []`: set only on a step where a replay stopped (status `error`): the outputs of its last good run, which the stale steps after it still reference. Cleared when a replay next gets past the step. Saved with the session.
  - `Session.edit(step_id: str, raw: dict) -> list[Step]`: validates `raw` as `"user"` (a complete param set, refs as ids or unique prefixes, stored as full ids); when the params differ from the stored ones, sets them, sets `edited=True` and appends a change note; either way marks the step and every later non-rejected step `stale`, emits `step.stale {"step_ids": [...]}` and calls `on_change`; returns the stale steps; runs nothing. Refuses (EngineError, nothing changed) bad params, unknown refs, an image whose first producer (`produced_by`) is the step itself or a later step unless an earlier step also outputs it (an import that a step makes again byte for byte stays usable), and any step at or after it that is `proposed`, `approved` or `running`.
  - `Session.replay_from(step_id: str, *, use_cache: bool = True) -> list[Step]`: re-executes the step and every later non-rejected step in order, remapping image refs old output -> new output by position, where the newest step before a reader that made an id decides what it means; a step whose remapped `cache_key` matches an earlier successful run whose outputs are all still in the store reuses that run's results without running (emits only `step.finished`); stops at the first failure (that step `error` with `previous_outputs` set; the rest stay `stale` with their last outputs and `cache_key`, but their refs already follow the new outputs of the steps that ran); returns every step it processed (run or reused), the failed one last. Refuses to start while an earlier step is `stale` or stopped (`previous_outputs`), or while a step in range is `proposed`/`approved`/`running`. `use_cache=False` runs every step (a faithful re-execution, spec §2 criterion 4).
  - `Session.delete_last(step_id: str) -> None`: EngineError unless it is the last step and not `proposed`/`approved`/`running`; removes the step and nothing else: its artifacts stay in the store, messages keep it in `step_ids`, artifacts keep it as `produced_by`, so Task 7's `_next_id` never gives its id to a new step while any of those name it; appends a change note; emits `step.deleted {"step_id": <the deleted step's id>}` (an event spec §7's list gains: Task 12 lists and forwards it, Task 13's carry-forward edit records it); calls `on_change`. A refused delete emits nothing.
  - `Session.referenced_ids() -> set[str]`: every step's image inputs, outputs and `previous_outputs`; message image parts; every artifact whose `produced_by` is a step that a message's `step_ids` names (deleted steps included: for a deleted step that is what is left of its outputs); every artifact whose short id (first 8 hex) appears in the text of the transcript (contents and tool-call arguments, at any depth) or of a message; and `original_id` of each of those. Task 9's save keeps only these, so a reopened session never loses a picture the chat or the model still points at.
  - Change notes (appended to `changes`, in Task 7's `"the user ran step N: ..."` style): `"the user edited step 2: cutout {"image": "a3f9c1d2", "box": [...], "no_ai": true}"`, `"the user replayed steps 2 to 4; step 4 now gives b4c5d6e7 (photo_paste)"`, `"the user replayed from step 2: step 3 (cutout) failed: <message>; later steps are stale"`, `"the user deleted step 4 (paste)"`.
  - Private: `_BUSY: dict[str, str]`, `_map_refs(tool: str, params: dict, fn: Callable[[str], str]) -> dict`, `_made(steps: list[Step]) -> set[str]`, `_advance(remap: dict[str, str], old: list[str], new: list[str]) -> None`; `Session._position`, `_refuse_busy`, `_refuse_later`, `_call`, `_executions`, `_reuse`, and the static `Session._mentioned(value: object, shorts: set[str]) -> set[str]`.

- [ ] **Step 1: Write the failing tests**

Every test runs real tools in-process (`filter`, `prep`, `cutout` without the background remover, `paste`) on a synthetic 240x180 JPEG, so nothing downloads and the file runs in about half a second. `Counting` wraps `InProcessExecutor` and records which tools really ran, which is how the tests tell a cache hit from a run. In `Rig.chain()` the paste reads two earlier steps (s2's piece as the base, s3's piece on top), so remapping is checked across more than one producer. The two Review Focus tests are `test_an_edit_that_breaks_a_later_step_stops_the_replay_there` (focus 4) and `test_byte_identical_outputs_keep_their_first_producer` (focus 2, the replay and delete half; Task 7 pins the store half). `test_referenced_ids_keep_what_the_chat_and_the_model_point_at` pins what a save keeps once steps are deleted (focus 2's save side; Task 9 saves, reopens and checks the deleted step's picture is there).

`core/tests/test_replay.py`:
```python
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
    lone = s.import_image(_png(), "lone.png")  # imported but never used
    s1 = s.run_tool("filter", {"image": rig.work.id, "names": ["invert"]}, "user")
    s.add_message("user", [Part(type="image", artifact_id=s1.outputs[0])])
    ids = s.referenced_ids()
    assert ids == {rig.work.id, rig.work.original_id, s1.outputs[0]}
    assert lone.id not in ids and rig.work.original_id != rig.work.id


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
    assert lone.id not in ids and lone.original_id not in ids
    assert ids == {rig.work.id, rig.work.original_id, s1.outputs[0], y, told.id, told.original_id,
                   said.id, said.original_id, shown.id, shown.original_id, glued.id, glued.original_id}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_replay.py -q`
Expected: `20 failed`, each with `AttributeError: 'Session' object has no attribute 'edit'` (Python adds `Did you mean: 'emit'?`), or `'replay_from'`, `'delete_last'`, `'referenced_ids'` (14 `edit`, 3 `replay_from`, 2 `delete_last`, 1 `referenced_ids`).

- [ ] **Step 3: Add `previous_outputs` to `Step`**

In `core/src/badshop/session/models.py`, in `class Step`, replace:
```python
    finished_at: float | None = None
    cache_key: str | None = None


class Part(BaseModel):
```
with:
```python
    finished_at: float | None = None
    cache_key: str | None = None
    # Only on a step where a replay stopped (status "error"): the outputs of its last good run, which the
    # stale steps after it still reference. The next replay that gets past it maps them to its new
    # outputs; it is saved with the session, so reopening a project in between loses nothing.
    previous_outputs: list[str] = []


class Part(BaseModel):
```

- [ ] **Step 4: Implement edit, replay, delete and referenced_ids**

In `core/src/badshop/session/session.py`, replace the first standard-library imports:
```python
import json
import re
import threading
import time
```
with:
```python
import copy
import json
import re
import threading
import time
```

Replace the end of Task 7's `_image_refs` (the module function just above `label_for`):
```python
            refs.extend(value if is_list else [value])
    return refs
```
with:
```python
            refs.extend(value if is_list else [value])
    return refs


# Steps the approval gate or a tool still owns: edit, replay and delete refuse to touch them.
_BUSY = {"proposed": "is waiting for approval", "approved": "is about to run", "running": "is running"}


def _map_refs(tool: str, params: dict, fn: Callable[[str], str]) -> dict:
    """A copy of stored params with every image ref passed through fn (replay's remap, short ids)."""
    out = dict(params)
    for name, is_list in registry.image_fields(registry.get(tool).params).items():
        value = out.get(name)
        if value is not None:
            out[name] = [fn(v) for v in value] if is_list else fn(value)
    return out


def _made(steps: list[Step]) -> set[str]:
    """Every artifact these steps output, a stopped replay's previous_outputs included."""
    return {id for s in steps for id in s.outputs + s.previous_outputs}


def _advance(remap: dict[str, str], old: list[str], new: list[str]) -> None:
    """Replay's table after a step made `new` where it used to make `old`: a later reference to its old
    output i now means its new output i. The newest producer before a reader wins, so an id this step
    makes again (or no longer makes) stops pointing at whatever an earlier step made in its place."""
    for i, o in enumerate(old):
        n = new[i] if i < len(new) else o
        if n != o:
            remap[o] = n
        else:
            remap.pop(o, None)
```

Replace `take_changes`, the last method of `class Session`:
```python
    def take_changes(self) -> list[str]:
        changes, self.changes = self.changes, []
        return changes
```
with:
```python
    def take_changes(self) -> list[str]:
        changes, self.changes = self.changes, []
        return changes

    # edit, replay, delete (spec 5.3, 7)

    def _position(self, step_id: str) -> int:
        step = self.step(step_id)  # an unknown id is step()'s clean EngineError
        return next(i for i, s in enumerate(self.data.steps) if s is step)

    @staticmethod
    def _refuse_busy(steps: list[Step]) -> None:
        for s in steps:
            if s.status in _BUSY:
                hint = ("approve or reject it first (the approval prompt can change its parameters)"
                        if s.status == "proposed" else "wait for it to finish, or press Stop")
                raise EngineError(f"step {s.index} ({s.tool}) {_BUSY[s.status]}", hint=hint)

    def _refuse_later(self, step: Step, pos: int, params: dict) -> None:
        """The timeline runs top to bottom: a step reads imports and what earlier steps made, never a
        picture that first came from itself or a later step. An artifact counts by its first producer,
        so an import that a step happens to make again (prep of a working copy gives the same bytes)
        is still the user's import, and a step may read it."""
        mine = {s.id for s in self.data.steps[pos:]}
        earlier = _made(self.data.steps[:pos])
        for id in _image_refs(step.model_copy(update={"params": params})):
            meta = self.artifacts.meta.get(id)
            if id in earlier or meta is None or meta.produced_by not in mine:
                continue
            maker = self.step(meta.produced_by)
            why = "it is this step's own output" if maker is step else f"step {maker.index} makes it later"
            raise EngineError(f"step {step.index} can't use {short(id)}: {why}",
                              hint="use an imported image or one an earlier step made")

    def _call(self, step: Step) -> str:
        """A step's call as a change note shows it: the params that differ from the defaults, short ids."""
        shown = registry.get(step.tool).params.model_validate(step.params).model_dump(mode="json",
                                                                                     exclude_defaults=True)
        return f"{step.tool} {json.dumps(_map_refs(step.tool, shown, short), ensure_ascii=False)}"

    def edit(self, step_id: str, raw: dict) -> list[Step]:
        """Give a finished (or failed, stale or rejected) step new params, as the user. It and every later
        step that was not rejected become `stale`; nothing runs until replay_from. Stale steps keep their
        old outputs and cache_key, which is how the replay finds results it can reuse. Params equal to the
        stored ones still mark the steps stale, but are not an edit: no `edited` flag, no change note."""
        pos = self._position(step_id)
        step = self.data.steps[pos]
        self._refuse_busy(self.data.steps[pos:])
        params = self._resolved(runner.validate(step.tool, raw, "user"))
        self._refuse_later(step, pos, params)
        changed = params != step.params
        if changed:
            step.params, step.edited = params, True
        stale = [step] + [s for s in self.data.steps[pos + 1:] if s.status != "rejected"]
        for s in stale:
            s.status = "stale"
        if changed:
            self.changes.append(f"the user edited step {step.index}: {self._call(step)}")
        self.emit("step.stale", {"step_ids": [s.id for s in stale]})
        self._changed()
        return stale

    def _executions(self) -> dict[str, Step]:
        """The successful runs the steps remember, by cache_key: done steps, and stale steps whose last
        run worked. Copies, so a replay that overwrites a step still finds what that step had."""
        return {s.cache_key: s.model_copy(deep=True) for s in self.data.steps
                if s.cache_key and s.error is None and s.status in ("done", "stale")}

    def _reuse(self, step: Step, hit: Step, key: str) -> None:
        """Take a remembered run's results instead of running: no step.started, only step.finished."""
        step.outputs, step.result_text = list(hit.outputs), hit.result_text
        step.data = copy.deepcopy(hit.data)
        step.status, step.error, step.cache_key = "done", None, key
        step.started_at = step.finished_at = time.time()
        self._emit("step.finished", step, step.outputs)

    def replay_from(self, step_id: str, *, use_cache: bool = True) -> list[Step]:
        """Re-execute a step and every later step that was not rejected, in order (spec 5.3).

        A reference to an old output of a re-executed step becomes the new output in the same position.
        A step whose rewritten params give the cache_key of an earlier successful run, all of whose outputs
        are still in the store, takes that run's results without running (use_cache=False runs every
        step). Stops at the first failure: that step is `error`, the steps after it stay `stale`, and
        their references already follow what the steps before the failure made. Returns the steps it
        processed, run or reused, the failed one last."""
        pos = self._position(step_id)
        behind = next((s for s in self.data.steps[:pos] if s.status == "stale" or s.previous_outputs), None)
        if behind is not None:  # these steps would run on inputs that are about to change
            raise EngineError(f"step {behind.index} ({behind.tool}) comes first and is not up to date",
                              hint=f"replay from step {behind.index} (if it failed, edit it first)")
        todo = [s for s in self.data.steps[pos:] if s.status != "rejected"]
        self._refuse_busy(todo)
        cache = self._executions() if use_cache else {}
        fresh = [s for s in todo if s.status != "stale"]
        for s in fresh:
            s.status = "stale"
        if fresh:
            self.emit("step.stale", {"step_ids": [s.id for s in fresh]})
        remap: dict[str, str] = {}
        processed: list[Step] = []
        failed: Step | None = None
        for step in todo:
            if remap:
                step.params = _map_refs(step.tool, step.params, lambda id: remap.get(id, id))
            old = list(step.outputs or step.previous_outputs)
            key = cache_key(step.tool, step.params)
            hit = cache.get(key)
            if hit is not None and all(id in self.artifacts for id in hit.outputs):
                self._reuse(step, hit, key)
            else:
                self._execute(step)  # never raises for the tool's failure; writes no change note
            processed.append(step)
            if step.status != "done":
                step.previous_outputs, failed = old, step
                break
            step.previous_outputs = []
            if use_cache:
                cache[key] = step.model_copy(deep=True)
            _advance(remap, old, step.outputs)
        if failed is not None:
            # The next replay starts at the failed step with an empty table, so the steps after it take
            # what ran before it now. They keep their last run (outputs, cache_key: still a true cache
            # entry) and stay stale. The failed step and each of them still stand for what they made
            # last time, so a reference to that stays put.
            _advance(remap, failed.previous_outputs, failed.previous_outputs)
            for rest in todo[len(processed):]:
                if remap:
                    rest.params = _map_refs(rest.tool, rest.params, lambda id: remap.get(id, id))
                made = rest.outputs or rest.previous_outputs
                _advance(remap, made, made)
            self.changes.append(f"the user replayed from step {todo[0].index}: step {failed.index} "
                                f"({failed.tool}) failed: {failed.error.message}; later steps are stale")
        elif processed:
            last = processed[-1]
            made = ", ".join(self._named(i) for i in last.outputs)
            self.changes.append(f"the user replayed steps {processed[0].index} to {last.index}"
                                + (f"; step {last.index} now gives {made}" if made else ""))
        self._changed()
        return processed

    def delete_last(self, step_id: str) -> None:
        """Delete the last step (spec 7: the last step only, in v1) and emit `step.deleted {"step_id"}`,
        an event spec 7's list gains here, so every client drops the step's card. Nothing else is
        rewritten: its artifacts stay in the store (a message, another step or an export may still show
        them), a message that lists it keeps listing it, and an artifact it made first keeps it as
        produced_by. Those records are what stop Task 7's _next_id from giving its id to a new step, and
        what lets referenced_ids keep the pictures a message's deleted step made."""
        step = self.step(step_id)
        last = self.data.steps[-1]
        if step is not last:
            raise EngineError(f"only the last step can be deleted, and step {step.index} is not the last",
                              hint=f"delete step {last.index} first, then work backwards")
        self._refuse_busy([step])
        self.data.steps.pop()
        self.changes.append(f"the user deleted step {step.index} ({step.tool})")
        self.emit("step.deleted", {"step_id": step.id})
        self._changed()

    @staticmethod
    def _mentioned(value: object, shorts: set[str]) -> set[str]:
        """The short ids in `shorts` that appear in any string inside `value`, a JSON value such as the
        transcript (contents and tool-call arguments) or a list of message texts. A short id counts
        wherever it sits in a run of hex digits, so a full id or a longer prefix mentions it too. Walked
        with a list, not recursion, because a transcript read from a project file may nest deeply."""
        found: set[str] = set()
        todo = [value]
        while todo:
            item = todo.pop()
            if isinstance(item, str):
                for run in re.findall(r"[0-9a-f]{8,}", item):
                    found |= shorts.intersection(run[i:i + 8] for i in range(len(run) - 7))
            elif isinstance(item, dict):
                todo.extend(item.values())
            elif isinstance(item, list):
                todo.extend(item)
        return found

    def referenced_ids(self) -> set[str]:
        """The artifacts the session still points at, which project save (Task 9) keeps: every step's
        inputs and outputs (and a stopped replay's previous_outputs); the images in messages; what each
        step a message names made first (its produced_by), which for a deleted step is what is left of
        its outputs; every artifact whose short id appears in the transcript or in a message's text; and
        the originals of all of those that are imports. So a reopened session never loses a picture the
        chat or the model still points at."""
        meta = self.artifacts.meta
        ids: set[str] = set()
        for s in self.data.steps:
            ids.update(_image_refs(s), s.outputs, s.previous_outputs)
        named: set[str] = set()
        texts: list[str] = []
        for m in self.data.messages:
            named.update(m.step_ids)
            ids.update(p.artifact_id for p in m.content if p.type == "image" and p.artifact_id)
            texts.extend(p.text for p in m.content if p.text)
        ids.update(i for i, a in meta.items() if a.produced_by in named)
        by_short: dict[str, list[str]] = {}
        for i in meta:
            by_short.setdefault(short(i), []).append(i)
        for found in self._mentioned([self.data.transcript, texts], set(by_short)):
            ids.update(by_short[found])
        originals = [meta[i].original_id for i in ids if i in meta]
        ids.update(o for o in originals if o)
        return ids
```

Notes on the design (what the brief left open, and why):
- **The cache is the steps themselves.** `_executions()` collects, when a replay starts, every done step and every stale step whose last run succeeded (`error is None`), keyed by `cache_key`. That works because neither `edit` nor a stopped replay touches a stale step's outputs or `cache_key`: a stale step still describes its last run, whatever its params say now, and the edited step's old run stays findable under its old key. Runs made during the replay are added as it goes, so two identical calls in one replay run once. Because it is all in `data.steps`, the cache survives save and open with no extra state; a run an earlier replay overwrote is forgotten, and re-running it gives the same bytes, only slower. The key covers the input bytes, since stored params hold full artifact ids (content hashes).
- **A step's own results count, and so do other steps' results.** When an edit makes step 1 ask exactly what step 2 asked, step 1 takes step 2's outputs without running (`test_a_step_can_take_another_steps_result`).
- **Remapping is positional, and the newest producer wins.** `_advance` records each processed step: its old output i now means its new output i (by position; if a network tool now returns fewer candidates, a later step that used a vanished candidate keeps the old artifact, which is still in the store). An id is looked up once, never chased through the table. Two steps can make the same bytes (Review Focus 2), so an id a step makes again, unchanged, is dropped from the table: a reader after it reads that step's output, not what an earlier step now makes in its place (`test_byte_identical_outputs_keep_their_first_producer`). The same rule makes the SKILL.md flow work: `prep` of an imported working copy gives back the import's own id, so after an edit of `prep` the steps after it follow `prep`'s new copy, while `prep` itself keeps reading the import. Only processed steps' old outputs enter the table, so references to imports nothing re-made stay put. Rejected steps are skipped and keep their params: they never ran.
- **A stopped replay leaves the stale steps consistent.** Task 7's `_execute` clears a step's outputs when it starts, so a step that fails in a replay would lose the ids the stale steps after it still read, and the next successful replay could not remap them. `previous_outputs` keeps those ids on the failed step, `old = outputs or previous_outputs` picks them up next time, and they are part of `session.json`, so an autosave and a crash in between lose nothing. `referenced_ids` includes them, so save keeps those artifacts. The next replay starts at the failed step with an empty table, so before stopping, the replay rewrites the refs of the steps after the failure with the table it built. Without that, a stale step that also read an earlier re-executed step (s4 pasting onto s2's piece) would never learn s2's new output and would end up `done` on the old picture (`test_an_edit_that_breaks_a_later_step_stops_the_replay_there`). The newest-producer rule still holds there: the failed step, and then each stale step in turn, still stands for the pictures it made last time, so those ids leave the table before the steps after it are rewritten (`test_a_failed_step_still_stands_for_what_it_made`, `test_a_stopped_replay_leaves_a_reader_on_the_newest_step_that_made_its_picture`). The stale steps keep the outputs and `cache_key` of their last run, so the cache stays true.
- **Replays stay causal.** `replay_from` refuses to start below a stale or stopped step: the steps it would run read inputs that are about to change, and would end up `done` on stale pictures. `edit` refuses an image that first came from the step itself or a later step (its `produced_by`), unless an earlier step also outputs it, for the same reason (and because Task 9's recipe runs top to bottom). It goes by the first producer, not by who outputs the bytes now, because a step can re-make an import byte for byte: `prep` of a working copy lists the import among its outputs, and the user must still be able to edit that `prep`. An artifact whose first producer was deleted belongs to no step and reads like an import. All three methods refuse a `proposed`, `approved` or `running` step in their range, because the approval gate owns a waiting step and an edit under it would leave it pointing at replaced pictures; the hint says to approve or reject it first.
- **An edit that changes nothing is not an edit.** Pressing Apply & replay with the same params marks the steps stale, and the replay reuses every result from the cache. But `edited` stays as it was and no change note is written, like Task 7's `run`, which sets `edited` only when the params differ.
- **Events.** An edit emits one `step.stale` for the steps it marks. A replay emits `step.stale` for any done steps it marks stale first ("replay from here" on an unchanged chain), then `_execute`'s `step.started` and `step.finished`/`step.failed` for each run, and only `step.finished` for a reused result (payload per Task 7's `_emit`: the step and its outputs' metas). The refs a stopped replay rewrites on the stale steps after the failure get no event (spec §7 has none that carries a stale step's params); a client sees them in the next `session.get`. `delete_last` emits `step.deleted {"step_id": "s4"}`, an event spec §7's list lacks: without it a client (or a second window) would learn of a deletion only from its next `session.get` and keep showing the card meanwhile. Task 12 lists it with the other events and forwards it; Task 13's carry-forward edit records the addition. A refused edit, replay or delete emits nothing. `on_change` runs after every settled change, never with a step left `running`.
- **Deleting rewrites nothing but the step list.** The deleted step's artifacts stay in the store (Review Focus 2: nothing another step or a message references is ever removed; replay removes nothing either). A message keeps listing the step in `step_ids`, and an artifact it made first keeps it as `produced_by`. That is Task 7's design: `_next_id` hands out one past the highest number anything still names, so those records keep the id from coming back while they exist (`test_delete_last_only_deletes_the_last_finished_step` pins that the step after a deleted s4 is s5). A reader of the session treats an id with no step as a deleted step: `_stem` stops there, `_refuse_later` treats its artifacts like imports, and Task 9's open does not require step ids to resolve. An id nothing names (a failed step no message lists) can come back, and then nothing in the session points at the old step.
- **What save keeps (`referenced_ids`).** Task 9 stores only these artifacts, so the set must hold every picture something in the session still points at, or a save and open loses it. Steps, message images and the originals of imports are the obvious part. Two more pointers survive a deletion: a message's `step_ids` (the chat hangs that step's card on the reply) and the transcript (the model read the step's tool result, `key: a3f9c1d2 (label, WxH)`, and may name the picture again). So `referenced_ids` also keeps every artifact first made (`produced_by`) by a step a message names, deleted or not; for a deleted step that is all that records its outputs, and for a live one it adds the pictures it made before a replay, which the chat showed at the time. It also keeps every artifact whose short id appears in any string of the transcript (contents and tool-call arguments, at any depth) or in a message's text (a superset of what the transcript says, which costs nothing), wherever it sits in a run of hex digits, so a full id or a longer prefix counts too. Task 7's import note (`the user added image a3f9c1d2 (lincoln_work)`) reaches the transcript in the next turn's system note, so an import the agent has heard of is kept even if no step used it. A deleted step's output that another step made first (byte-identical bytes, Review Focus 2) has that step as `produced_by`; it is still kept while that step or any text points at it, and a message names only the agent's steps, whose tool results (with every output's short id) are in the transcript. False matches only keep an extra picture. The set is stable across save and open: the transcript, the messages and each kept artifact's `produced_by` go into `session.json`, so the reopened session references exactly what was saved (Task 9's open checks every referenced id is present). The walk uses a list instead of recursion, so a deeply nested transcript in a hostile project file can't raise `RecursionError`, and it is linear in the transcript's size (at most `MAX_SESSION_BYTES`), which every autosave pays.
- **One change note per user action.** `_execute` writes none, so a replay adds exactly one line (how far it got, and the newest output or the failure), and the agent sees the rest in the step summary.
- **`use_cache`.** With the cache on, "replay from here" on an unchanged chain re-runs nothing (every step matches its own last run). A faithful re-execution, like spec §2 criterion 4's "replaying it reproduces the same output pixels" after save and open, needs `use_cache=False`; `test_replay_of_unchanged_steps_runs_nothing_unless_the_cache_is_off` pins both.

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_replay.py -v`
Expected: `20 passed` in under a second, offline.

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1103 passed, 1 deselected` (Task 7's 1083 plus these 20; the deselected one is the `network` test), and ruff prints `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add core/src/badshop/session/models.py core/src/badshop/session/session.py core/tests/test_replay.py
git commit -m "feat(session): edit, replay with remapping and cache, delete the last step

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Project files (.badshop), recipe export (to_argv), autosave

**Files:**
- Modify: `core/src/badshop/cli/argparse_gen.py` (append `to_argv` and two private helpers after `add_tool_parser`)
- Create: `core/src/badshop/session/project.py`
- Test: `core/tests/test_project.py`

**Interfaces:**
- Consumes:
  - Plan 1: `argparse_gen._classify(annotation) -> tuple[str, Any]` (kinds `bool`, `choice`, `tuple`, `scalar`, `list_<kind>`) and `add_tool_parser` (the parser `to_argv` must invert); `registry.REGISTRY`, `registry.get(name) -> ToolSpec`, `registry.image_fields(params_cls) -> dict[str, bool]`; `ToolSpec.params/mutates/network`; `Params.POSITIONAL`, `Params.FLAGS`; `assets.data_dir() -> Path`; `EngineError(message, hint)` (`.message`, `.hint`); `cli.main.build_parser()`, `cli.main.main(argv) -> int` and its `run <recipe>` command (`recipes.cmd_run`); `tests/conftest.py` `FIXTURES`.
  - Task 2: `ToolSpec.writes_files`; `runner.validate(name: str, raw: dict, actor: str = "user") -> Params` (EngineError `"bad parameters for <name>"` with a hint); `runner.explain(e: ValidationError) -> str`.
  - Task 5: `models.SCHEMA`, `SessionData` (`schema_` aliased `"schema"`), `ArtifactMeta` (`.id`, `.label`, `.produced_by`, `.source`, `.original_id`, `.ext`), `Step`, `StepError`, `Part`; `artifacts.ArtifactStore()` (constructed with no arguments), `.meta`, `.add(data, label, *, produced_by=None, source=None, original_id=None) -> ArtifactMeta` (decodes only through `load_image(data, formats=IMPORT_FORMATS, max_pixels=MAX_IMPORT_PIXELS)`; bytes that don't decode, or are too big, raise `EngineError`), `.data(id) -> bytes`, `.ids()`, `.drop(ids)`, `id in store`; `artifacts.short(id)`.
  - Task 7: `Session(data, artifacts, *, executor=None, emit=None, output_dir=None, on_change=None)` (its `__init__` makes `data.artifacts` the store's `meta`), `Session.new(name, **kw)`, `.data`, `.artifacts`, `.output_dir`, `.import_image(data, label) -> ArtifactMeta`, `.add_message(role, parts, step_ids=())`, `.data.transcript` (a list of provider-format dicts; a tool result is `{"role": "tool", "tool_call_id", "content": step.result_text}`), `.propose(tool, raw, actor) -> Step`, `.reject(step_id, note)`, `.run_tool(tool, raw, actor) -> Step` (an engine failure gives a step with status `"error"`, it is not raised), `.step(step_id) -> Step`; `session.result_text(step, artifacts) -> str` (`"error: <message>\nhint: <hint>"` for a failed step).
  - Task 8: `Session.referenced_ids() -> set[str]` (ruling R6: besides every step's image inputs and outputs, message images, the outputs of every step a message's `step_ids` names, deleted steps included, and every artifact whose short id appears in the transcript or in a message's text, plus the originals of the imports among all of those), `Session.delete_last(step_id) -> None` (removes the last step; its artifacts stay in the store and keep it as `produced_by`), `Session.replay_from(step_id) -> list[Step]` (skips `rejected` steps and re-executes every other later step).
- Produces:
  - `cli/argparse_gen.to_argv(spec: ToolSpec, params: dict) -> list[str]`: the command line, tool name first (`argv[0] == spec.name`), that the generated parser reads back as `params`. Positionals in `POSITIONAL` order, then flags in field order (`FLAGS` or `--field-name`); fields missing or at their default are left out; tuples spelled out; list fields repeat their flag; `True` bools are bare flags. A flag value that starts with `-` is written `--flag=value`; if any positional value starts with `-`, the result is `[name, *flags, "--", *positionals]`. Raises `ValueError` only for a bool set to False whose default is True (no such field exists). A value that is exactly `--` reads back only on Pythons whose argparse keeps it (3.12.11 and 3.13 do; see the note after Step 3).
  - `session/project.py`: `EXT = ".badshop"`, `SESSION_JSON = "session.json"`, `RECIPE_JSON = "recipe.json"`, `MAX_SESSION_BYTES = 16 MiB`, `MAX_MEMBER_BYTES = 512 MiB`, `MAX_PROJECT_BYTES = 2 GiB` (uncompressed; shared by save and open), `READ_CHUNK = 1 MiB`, `METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)`;
    `save(session: Session, path: Path) -> Path` (appends `.badshop` when the suffix is missing, returns the path written; only `session.referenced_ids()` artifacts; JSON written as ASCII; EngineError "too big to open again", before anything is written, when the project exceeds the size limits; a new temp file in the same folder made with mode `0o666` minus the umask (or the replaced file's mode), fsync, `os.replace`; EngineError on any OS failure, with the temp file removed and the old file intact);
    `open_project(path: Path, **session_kw) -> Session` (every failure an EngineError; members compressed with anything but STORED or DEFLATED are refused; members are read `READ_CHUNK` at a time under a running cap; every id Task 7's `_next_id` reads must be one it makes, so a step id, a message's `step_ids` entry or an artifact's `produced_by` that doesn't fully match `STEP_ID = s[1-9][0-9]{0,8}`, or a message id that doesn't fully match `MESSAGE_ID = m[1-9][0-9]{0,8}`, is refused as damaged ("... an id badshop never makes"); a step saved as `proposed` comes back `rejected` with result_text `"rejected: badshop closed before it was approved"`, one saved as `approved` or `running` comes back `error` with `"badshop closed before this step finished"`);
    `export_recipe(session: Session) -> dict` (`{"vars": {}, "steps": [argv, ...]}`);
    `autosave_path() -> Path` (`assets.data_dir() / "autosave" / "session.badshop"`); `autosave(session) -> None` (raises like `save`); `find_autosave() -> Path | None` (this run's autosave, once its session has changed);
    `claim_autosave() -> Path | None` (spec §9 and §10: called once at launch, before the session can change. It `os.replace`s an existing `autosave/session.badshop` to `autosave/previous.badshop` and returns that path, so the new session's first autosave can't overwrite what the last run left. With nothing to move, a `previous.badshop` that no later run replaced is still returned. It returns None when there is neither. It creates nothing and never raises; a file it can't move stays where it is and None is returned). Task 12's `CoreApp.__init__` calls it and reports the result in the snapshot as `"restorable": str | None`, and the user-only `session.restore {}` opens that file through `_switch` with `path: None`.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_project.py`:
```python
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
    unused = s.import_image(png_bytes((40, 30), "orange"), "orange.png")  # never referenced
    path = project.save(s, tmp_path / "meme")
    assert path == tmp_path / "meme.badshop" and path.is_file()
    keep = s.referenced_ids()
    assert unused.id not in keep and unused.id in s.artifacts
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        payload = json.loads(zf.read("session.json"))
        recipe = json.loads(zf.read("recipe.json"))
    assert names == {"session.json", "recipe.json"} | {art(s, aid) for aid in keep}
    assert payload["schema"] == 1 and "schema_" not in payload and set(payload["artifacts"]) == keep
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
    "newer schema": (edited(lambda m, p: p.update(schema=2)), "newer badshop"),
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
```

`test_a_deleted_steps_picture_the_chat_still_points_at_is_saved_and_reopened` is review focus 2's save side (ruling R6). Three agent steps each make a new picture of lincoln. An assistant message's `step_ids` names the first. The transcript's tool result mentions the second's short id, and no message names that step. Nothing points at the third. All three are deleted with `delete_last`, then the session is saved and reopened. The first two pictures are in the project and back in the reopened store, still credited to their deleted steps. The short id the model saw still resolves, and the reopened session's `referenced_ids()` is the same set, so the next autosave keeps them too. The third picture is left out, so save still drops what nothing points at.

`test_a_bad_project_is_a_clean_error_and_changes_nothing` is review focus 3: a corrupt, truncated, non-zip, newer-schema or hostile project (`../../x`, `/tmp/x`, `..\..\x` members, bytes that don't match their id, a missing artifact, a member whose headers lie about its size, BZIP2 or LZMA members) gives a clean EngineError with a hint, and nothing is written. `open_project` never sees the caller's session, so the `snapshot(s) == before` check there is only a sanity check: the check that a failed open keeps the current session and its autosave belongs to CoreApp, and Task 12's `session.open` test makes it (a failed `session.open` leaves `session.get` unchanged). `test_an_id_badshop_never_makes_is_refused` is the same check for hand-edited ids. Task 7's `_next_id` reads every step id, message id, message `step_ids` entry and artifact `produced_by`, and calls `int()` on any suffix `isdigit()` accepts. So `"s²"` (`isdigit()` is true, `int()` refuses it) or a 5000-digit suffix (past `int()`'s 4300-digit limit) used to open fine, and then every `propose()` and `add_message()` raised a bare ValueError. The cases cover all four places, both prefixes, and the pattern's edges: ten digits, a leading zero, a non-ASCII digit that `int()` reads (`"m٣"`), and a trailing new line (which a `$` anchor would let through). `test_the_ids_badshop_makes_open_and_the_next_ones_follow` pins the other side: nine-digit ids open, and the next step and message get the ids after them. `test_a_zip_bomb_is_refused_without_inflating_it` measures, with `tracemalloc`, that a DEFLATE member whose headers claim 10 bytes is never inflated whole (a plain `zf.read(info)` peaks at 77 MiB on it). `test_a_reopened_session_replays_to_the_same_pixels` drops the produced artifacts before replaying so Task 8's cache can't reuse them and every step really runs (spec §2 criterion 4, §11). `test_steps_saved_mid_turn_are_rejected_or_failed_and_a_replay_never_runs_an_unapproved_one` replays after the reopen, as `auto_replay` does after an edit, and shows the unapproved proposal is skipped. `test_claim_autosave_sets_the_last_runs_autosave_aside_for_a_restore` covers spec §9's restore offer as a sequence of launches. A first launch finds nothing and creates nothing. The next launch sets the crashed run's autosave aside. A launch that changed nothing still offers it. A new session's first autosave leaves it whole, and it opens with its five steps. The launch after that offers the newer run's session. Task 12's tests cover the same offer through CoreApp: the snapshot's `restorable`, `session.restore`, and a second app's first change.

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_project.py -q`
Expected: a collection error, `ImportError: cannot import name 'to_argv' from 'badshop.cli.argparse_gen'`.

- [ ] **Step 3: Implement `to_argv`**

In `core/src/badshop/cli/argparse_gen.py`, append after the last line of `add_tool_parser` (which ends with):
```python
    if spec.mutates:
        s.add_argument("-o", "--out", dest="_out", default=None, metavar="OUT",
                       help="path for the main output")
    s.set_defaults(_tool=spec.name)
```
add, at the end of the file (two blank lines before the first `def`):
```python
def _plain(value: Any) -> Any:
    """Tuples as lists, so JSON params compare equal to a model's defaults."""
    return [_plain(v) for v in value] if isinstance(value, (list, tuple)) else value


def _option(flag: str, value: Any) -> list[str]:
    word = str(value)
    # argparse reads a word starting with "-" as the next option ("--rotate -1e-05", "--text -_-").
    return [f"{flag}={word}"] if word.startswith("-") else [flag, word]


def to_argv(spec: ToolSpec, params: dict) -> list[str]:
    """The command line (tool name first) that `add_tool_parser`'s parser reads back as `params`.

    `params` is a validated, JSON-safe dict such as a step's params. Positional fields come first, in
    POSITIONAL order, then flags in field order (FLAGS or --field-name). Fields missing from `params` or at
    their default are left out, tuples are spelled out, lists repeat their flag, and True bools are bare
    flags. A flag value starting with "-" is written --flag=value; positional values that start with "-"
    go after a "--", with every flag before it. One value depends on the Python reading it back: a word
    that is exactly "--". Python 3.12.11 and 3.13 keep it; older 3.12 releases drop it (a caption of "--"
    parses as text=[] on 3.12.0 and 3.12.5), which the tool then refuses as bad parameters."""
    model = spec.params
    positional: list[str] = []
    flags: list[str] = []
    for name, f in model.model_fields.items():
        if name not in params:
            continue
        value = _plain(params[name])
        if not f.is_required() and value == _plain(f.get_default(call_default_factory=True)):
            continue
        if name in model.POSITIONAL:
            positional += [str(v) for v in value] if isinstance(value, list) else [str(value)]
            continue
        kind, _ = _classify(f.annotation)
        flag = model.FLAGS.get(name, "--" + name.replace("_", "-"))
        if kind == "bool":
            if value is not True:  # store_true flags can only switch a False default on
                raise ValueError(f"{spec.name}: {name}={value!r} can't be written as a command-line flag")
            flags.append(flag)
        elif kind == "tuple":
            flags += [flag, *map(str, value)]  # whole numbers: "-5" is read as a value, not an option
        elif kind == "list_tuple":
            for item in value:
                flags += [flag, *map(str, item)]
        elif kind.startswith("list_"):
            for item in value:
                flags += _option(flag, item)
        else:
            flags += _option(flag, value)
    if any(word.startswith("-") for word in positional):
        return [spec.name, *flags, "--", *positional]
    return [spec.name, *positional, *flags]
```

Why `--flag=value` and `--`: argparse reads any word that starts with `-` and isn't a plain negative number as an option, so `--rotate -1e-05` and a caption like `-_-` fail to parse. The `=` form works for every single-value flag, and after a `--` every word is positional. Tuple fields are whole numbers, and `-5` is read as a value because no badshop option looks like a negative number. This whole task's tests (every RICH sample, both variants, and the `-_-` recipe step included) pass on Python 3.12.0, 3.12.5 and 3.12.11.

One value depends on the Python: a word that is exactly `--`. Older 3.12 releases strip it from positional values, so to_argv's `["text", "--", "a.png", "--"]` reads back as `text=[]` on 3.12.0 and 3.12.5, and 3.12.0 also turns `--text=--` into `[]`. The newer argparse keeps it on 3.12.11 and 3.13.5. No spelling survives the old behaviour, because the value `--` in the second positional slot is always stripped. The failure is clean, never a different picture: the tool refuses `[]` as bad parameters, so `badshop run` stops at that step. The project's `.python-version` is `3.12`, which uv fills with a current 3.12 release (3.12.11 here). The Python floor (`>=3.12`) is a global constraint, so this task documents the limitation instead of raising the floor. The RICH samples hold no `--` value, so the round-trip test passes on every allowed Python.

- [ ] **Step 4: Implement project files, the recipe and autosave**

`core/src/badshop/session/project.py`:
```python
"""Project files (.badshop), the CLI recipe inside them, and the autosave.

A project is a zip: `session.json` (the SessionData, `"schema": 1`), `artifacts/<sha256><ext>` for every
artifact the session references, and `recipe.json` (the finished edits as a `badshop run` recipe). A
project may come from anywhere, so opening one trusts nothing in it: member names are never used as paths,
only the two compression methods badshop writes are accepted, sizes are checked before anything is read
and members are read a chunk at a time, every artifact must hash to its id and decode as an image, and
every failure is an EngineError. save refuses a project over the same size limits, so badshop never
writes a file it would then refuse to open.
"""

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from badshop.cli.argparse_gen import to_argv
from badshop.engine import assets
from badshop.engine.errors import EngineError
from badshop.session.artifacts import ArtifactStore, short
from badshop.session.models import SCHEMA, ArtifactMeta, SessionData, StepError
from badshop.session.session import Session, result_text
from badshop.tools import runner
from badshop.tools.registry import REGISTRY, image_fields

EXT = ".badshop"
SESSION_JSON = "session.json"
RECIPE_JSON = "recipe.json"
ARTIFACT_MEMBER = re.compile(r"^artifacts/([0-9a-f]{64})\.[a-z]{3,4}$")
ARTIFACT_ID = re.compile(r"^[0-9a-f]{64}$")
# The ids Session._next_id makes (s1, s2... and m1, m2...: ASCII digits, no leading zero). It reads every
# step and message id a session names, and int() fails on some others ("s²", thousands of digits). Nine
# digits is far past any real session. Matched with fullmatch, so a trailing new line is refused too.
STEP_ID = re.compile(r"s[1-9][0-9]{0,8}")
MESSAGE_ID = re.compile(r"m[1-9][0-9]{0,8}")
# Size limits, uncompressed, shared by save and open_project. session.json has its own, smaller one:
# json.loads and pydantic turn 16 MB of the worst-shaped JSON into about 1 GB of objects.
MAX_SESSION_BYTES = 16 * 2**20
MAX_MEMBER_BYTES = 512 * 2**20  # one artifact
MAX_PROJECT_BYTES = 2 * 2**30  # session.json and every artifact together
READ_CHUNK = 2**20
# The only compression methods badshop writes. zipfile inflates BZIP2 and LZMA members with no output
# limit at all, so a few KB of them can become gigabytes before any size check sees a byte.
METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
DAMAGED_HINT = "it may have been cut short or changed by something else; open another copy"
TOO_BIG_HINT = ("export the pictures you want to keep and start a new session for more; large imported "
                "originals (uncompressed BMP or TIFF files) take the most room")
# A step saved while it waited for approval or ran has no turn or tool left to finish it after a reopen.
# One nobody approved is rejected, as a stopped turn rejects what waits (ApprovalGate.cancel_all), so no
# replay ever runs it; one that was approved or running failed.
UNAPPROVED_TEXT = "rejected: badshop closed before it was approved"
INTERRUPTED = ("approved", "running")
INTERRUPTED_ERROR = StepError(message="badshop closed before this step finished",
                              hint="replay the step to run it again")

# What zipfile and zlib raise on a damaged archive (JSON and pydantic errors are handled first).
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError, RuntimeError,
               NotImplementedError, struct.error, zlib.error)


def _member(meta: ArtifactMeta) -> str:
    return f"artifacts/{meta.id}{meta.ext}"


def _mb(n: int) -> str:
    return f"{n / 2**20:,.1f} MB"


def _size_problem(session_bytes: int, artifact_bytes: dict[str, int]) -> str | None:
    """Why a project whose members have these uncompressed sizes is too big to open, or None."""
    if session_bytes > MAX_SESSION_BYTES:
        return f"session.json is {_mb(session_bytes)}, over the {_mb(MAX_SESSION_BYTES)} limit"
    for aid, size in artifact_bytes.items():
        if size > MAX_MEMBER_BYTES:
            return f"artifact {short(aid)} is {_mb(size)}, over the {_mb(MAX_MEMBER_BYTES)} limit"
    total = session_bytes + sum(artifact_bytes.values())
    if total > MAX_PROJECT_BYTES:
        return f"{_mb(total)} in all, over the {_mb(MAX_PROJECT_BYTES)} limit"
    return None


def export_recipe(session: Session) -> dict:
    """The session's finished edits as a CLI recipe, `{"vars": {}, "steps": [argv, ...]}`.

    Only done steps of tools that make images locally are included (not read-only looks, not network
    sources, not export). Image refs become `artifacts/<id><ext>` and each step writes its first output to
    `-o artifacts/<id><ext>`, so `badshop run recipe.json` inside an unzipped project rebuilds them."""

    def path_of(aid: str) -> str:
        meta = session.artifacts.meta.get(aid)
        if meta is None:
            raise EngineError(f"artifact {short(aid)} is missing from the session",
                              hint="this is a bug in badshop; export the images you want to keep")
        return _member(meta)

    steps = []
    for step in session.data.steps:
        spec = REGISTRY.get(step.tool)
        if step.status != "done" or spec is None or not spec.mutates or spec.network or spec.writes_files:
            continue
        params = dict(step.params)
        for name, is_list in image_fields(spec.params).items():
            value = params.get(name)
            if value:
                params[name] = [path_of(v) for v in value] if is_list else path_of(value)
        argv = to_argv(spec, params)
        if step.outputs:  # before any "--": after it, "-o" would be read as a positional value
            at = argv.index("--") if "--" in argv else len(argv)
            argv[at:at] = ["-o", path_of(step.outputs[0])]
        steps.append(argv)
    return {"vars": {}, "steps": steps}


def save(session: Session, path: Path) -> Path:
    """Write the session to `path` (".badshop" is added when missing) and return the path written.

    Only the artifacts the session references are stored. The zip is written to a new temporary file in
    the same folder and moved over `path` in one step, so a crash mid-save leaves the previous file whole.
    The file gets the mode any saved file gets (the umask decides), or keeps the mode of the file it
    replaces. A project over open_project's size limits is refused before anything is written."""
    path = Path(path)
    if path.suffix.lower() != EXT:
        path = path.with_name(path.name + EXT)
    keep = sorted(session.referenced_ids())
    missing = [aid for aid in keep if aid not in session.artifacts]
    if missing:
        raise EngineError(f"can't save: artifact {short(missing[0])} is missing from the session",
                          hint="this is a bug in badshop; export the images you want to keep")
    payload = session.data.model_dump(mode="json", by_alias=True)
    payload["artifacts"] = {aid: session.artifacts.meta[aid].model_dump(mode="json", by_alias=True)
                            for aid in keep}
    # Plain ASCII JSON: a lone surrogate (which a JSON client can send in any text) is written as an
    # escape and read back unchanged, where UTF-8 could not encode it at all.
    session_json = json.dumps(payload, indent=1).encode("ascii")
    recipe_json = (json.dumps(export_recipe(session), indent=2) + "\n").encode("ascii")
    problem = _size_problem(len(session_json), {aid: len(session.artifacts.data(aid)) for aid in keep})
    if problem:
        raise EngineError(f"can't save {path.name}: the project would be too big to open again ({problem})",
                          hint=TOO_BIG_HINT)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.part")
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # "x" makes a new file the way any saved file is made, so the umask sets its mode (mkstemp's 0600
        # would stay on the project after os.replace). An existing project keeps its own mode.
        with open(tmp, "xb") as fh:
            created = True
            with zipfile.ZipFile(fh, "w") as zf:
                zf.writestr(SESSION_JSON, session_json, zipfile.ZIP_DEFLATED)
                zf.writestr(RECIPE_JSON, recipe_json, zipfile.ZIP_DEFLATED)
                for aid in keep:  # PNG, JPEG and GIF are compressed already: store them as they are
                    zf.writestr(_member(session.artifacts.meta[aid]), session.artifacts.data(aid))
            fh.flush()
            os.fsync(fh.fileno())
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException as e:
        if created:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        if isinstance(e, OSError):
            raise EngineError(f"can't save {path} ({e})", hint="check the folder exists and is writable, "
                              "and the disk isn't full") from None
        raise
    return path


def _damaged(path: Path, what: str, hint: str = DAMAGED_HINT) -> EngineError:
    return EngineError(f"{path.name} is damaged: {what}", hint=hint)


def _too_big(path: Path, what: str) -> EngineError:
    return EngineError(f"{path.name} is too big to open ({what})",
                       hint="badshop never saves a project this big, so something else changed or made it; "
                            "open another copy")


def _unsafe(name: str) -> bool:
    """A member name that would land outside a folder if anything ever extracted it."""
    return (name.startswith("/") or "\\" in name or bool(re.match(r"[A-Za-z]:", name))
            or ".." in PurePosixPath(name).parts)


def _index(path: Path, zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Artifact id -> member. Refuses names that could climb out of a folder and compression methods
    badshop never writes (every member, read or not)."""
    found: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        if _unsafe(info.filename):
            raise EngineError(f"{path.name} isn't a safe badshop project: it holds a file named "
                              f"{info.filename!r}",
                              hint="badshop never writes names like that; don't open this file")
        if info.compress_type not in METHODS:
            raise EngineError(f"{path.name} isn't a badshop project: {info.filename!r} is compressed in a "
                              "way badshop never writes", hint="open a .badshop file saved by badshop")
        m = ARTIFACT_MEMBER.match(info.filename)
        if m:
            if m[1] in found:
                raise _damaged(path, f"artifact {short(m[1])} is stored twice")
            found[m[1]] = info
    return found


def _read(path: Path, zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    """A member's bytes, never more than `cap` of them in memory.

    The declared size is checked first, but it can lie: zipfile cuts a member down to its declared size
    (then fails its CRC) only after inflating, and one read() of a DEFLATE member may inflate up to 2 GiB.
    Reading a chunk at a time keeps every inflate step small, and the running total is checked as it
    grows, so this holds whatever the headers say."""
    if info.file_size > cap:
        raise _too_big(path, f"{info.filename} is {_mb(info.file_size)}, over the {_mb(cap)} limit")
    chunks: list[bytes] = []
    total = 0
    with zf.open(info) as fh:
        while chunk := fh.read(READ_CHUNK):
            total += len(chunk)
            if total > cap:
                raise _too_big(path, f"{info.filename} holds more than {_mb(cap)}")
            chunks.append(chunk)
    return b"".join(chunks)


def _session_data(path: Path, raw: bytes) -> SessionData:
    try:
        payload = json.loads(raw)
    except ValueError as e:  # UnicodeDecodeError is a ValueError too
        raise _damaged(path, f"session.json isn't JSON ({e})") from None
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if type(schema) is not int or schema < 1:
        raise _damaged(path, "session.json has no schema number")
    if schema > SCHEMA:
        raise EngineError(f"{path.name} was saved by a newer badshop (project schema {schema}; "
                          f"this badshop reads schema {SCHEMA})", hint="update badshop to open it")
    try:
        data = SessionData.model_validate(payload)
    except ValidationError as e:
        raise _damaged(path, "session.json isn't a badshop session", hint=runner.explain(e)) from None
    for step in data.steps:
        if step.tool not in REGISTRY:
            raise _damaged(path, f"step {step.index} uses a tool this badshop doesn't have ({step.tool})",
                           hint="update badshop to open it")
        try:  # stored params were validated when the step was made; anything else was changed since
            runner.validate(step.tool, step.params)
        except EngineError as e:
            raise _damaged(path, f"step {step.index} ({step.tool}) has bad parameters", hint=e.hint) from None
    for aid, meta in data.artifacts.items():
        if not ARTIFACT_ID.match(aid) or meta.id != aid:
            raise _damaged(path, f"artifact {aid[:16]!r} is listed under the wrong id")
    # every id Session._next_id reads: an odd one would make each later propose() or add_message() fail
    named = [(f"step {step.index} has", step.id, STEP_ID) for step in data.steps]
    for n, message in enumerate(data.messages, 1):
        named.append((f"message {n} has", message.id, MESSAGE_ID))
        named += [(f"message {n} names a step by", sid, STEP_ID) for sid in message.step_ids]
    named += [(f"artifact {short(aid)} names its step by", meta.produced_by, STEP_ID)
              for aid, meta in data.artifacts.items() if meta.produced_by is not None]
    for what, name, pattern in named:
        if not pattern.fullmatch(name):
            raise _damaged(path, f"{what} an id badshop never makes ({name[:16]!r})")
    return data


def _finish_interrupted(data: SessionData, artifacts: ArtifactStore) -> None:
    """Steps saved while waiting for approval or running (an autosave taken mid-turn): nothing can finish
    them after a reopen, because the turn and the worker are gone."""
    now = time.time()
    for step in data.steps:
        if step.status == "proposed":
            step.status, step.finished_at, step.result_text = "rejected", now, UNAPPROVED_TEXT
        elif step.status in INTERRUPTED:
            step.status, step.finished_at = "error", now
            step.error = INTERRUPTED_ERROR.model_copy()
            step.result_text = result_text(step, artifacts)


def open_project(path: Path, **session_kw) -> Session:
    """Open a project as a new Session (`session_kw` go to Session: executor, emit, output_dir, on_change).

    Reads only session.json and the listed `artifacts/<sha256><ext>` members, a chunk at a time and within
    the size limits. Checks the schema (a newer one is refused), every step's tool and params, that every
    step and message id is one badshop makes, every artifact's hash and that it decodes as an image badshop
    imports, and that every artifact the session references is present. A step saved while waiting for
    approval comes back rejected; one saved while approved or running comes back failed. Every failure is
    an EngineError; nothing outside the returned Session changes."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            members = _index(path, zf)
            try:
                info = zf.getinfo(SESSION_JSON)
            except KeyError:
                raise EngineError(f"{path.name} isn't a badshop project (it has no session.json)",
                                  hint="open a .badshop file saved by badshop") from None
            data = _session_data(path, _read(path, zf, info, MAX_SESSION_BYTES))
            missing = [aid for aid in data.artifacts if aid not in members]
            if missing:
                raise _damaged(path, f"artifact {short(missing[0])} is missing")
            problem = _size_problem(info.file_size, {aid: members[aid].file_size for aid in data.artifacts})
            if problem:
                raise _too_big(path, problem)
            artifacts = ArtifactStore()
            for aid, meta in data.artifacts.items():
                blob = _read(path, zf, members[aid], MAX_MEMBER_BYTES)
                if hashlib.sha256(blob).hexdigest() != aid:
                    raise _damaged(path, f"artifact {short(aid)} doesn't match its id")
                try:  # decodes through the import formats only (never EPS), within MAX_IMPORT_PIXELS
                    artifacts.add(blob, meta.label, produced_by=meta.produced_by, source=meta.source,
                                  original_id=meta.original_id)
                except EngineError as e:
                    raise _damaged(path, f"artifact {short(aid)} can't be opened: {e.message}") from None
    except EngineError:
        raise
    except (FileNotFoundError, IsADirectoryError, PermissionError) as e:
        raise EngineError(f"can't open {path} ({e.strerror or e})", hint="check the path") from None
    except _ZIP_ERRORS as e:
        raise EngineError(f"{path.name} isn't a badshop project, or it is damaged ({type(e).__name__}: {e})",
                          hint="open a .badshop file saved by badshop; " + DAMAGED_HINT) from None
    _finish_interrupted(data, artifacts)
    session = Session(data, artifacts, **session_kw)  # Session makes data.artifacts the store's metas
    missing = session.referenced_ids() - set(artifacts.ids())
    if missing:
        raise _damaged(path, f"artifact {short(min(missing))} is missing")
    return session


def autosave_path() -> Path:
    """Where the open session is saved after every change (spec §9)."""
    return assets.data_dir() / "autosave" / f"session{EXT}"


def autosave(session: Session) -> None:
    """Save the open session to the data dir (spec §9); raises EngineError like save."""
    save(session, autosave_path())


def find_autosave() -> Path | None:
    """This run's autosave, once its session has changed (claim_autosave set the last run's aside)."""
    path = autosave_path()
    return path if path.is_file() else None


def claim_autosave() -> Path | None:
    """Set the autosave the last run left behind out of this run's way, and return it (None: there is none).

    A core calls this once at launch, before its session can change. Every autosave replaces
    `autosave/session.badshop`, so without this the new session's first change would overwrite what a
    crashed run left there before anyone could restore it (spec §9: the next launch offers to restore it;
    §10: a restarted core reopens it). The file is moved to `autosave/previous.badshop` and that path is
    returned. With nothing to move (the last run changed nothing, or crashed again before it did), a
    previous.badshop that no later run replaced is still returned, so the offer outlives a crash loop.
    Creates nothing and never raises: a file that can't be moved stays where it is and None is returned
    (a folder that refuses the rename usually refuses the autosave's temp file too, so the file waits for the
    next launch)."""
    path = autosave_path()
    previous = path.with_name(f"previous{EXT}")
    try:
        with contextlib.suppress(FileNotFoundError):
            os.replace(path, previous)
        return previous if previous.is_file() else None
    except OSError:
        return None
```

Notes:
- Opening never extracts, so member names are never paths. It still refuses names that would escape a folder (absolute, `..`, a backslash, a drive letter), because review focus 3 counts such a file as hostile. Unknown members with safe names (`__MACOSX/...`, or anything a later schema-1 badshop adds) are ignored. Only artifacts listed in `session.json` are read.
- Zip bombs. zipfile cuts a member down to its declared size, then checks the CRC, but only after it has inflated the data. BZIP2 and LZMA members inflate with no output limit, and one `read()` of a DEFLATE member inflates up to 2 GiB. So `_index` refuses any member (read or not) whose method isn't STORED or DEFLATED, which are the only two badshop writes. `_read` checks the declared size, then reads `READ_CHUNK` at a time with a running total against the cap. That keeps every inflate step to about 1 MiB, whatever the headers say. Measured in a clone with session.json's headers claiming 10 bytes: a 459-byte BZIP2 member (400 MiB of spaces) is refused as soon as it is listed, and a 400 KB DEFLATE member ends in a clean "Bad CRC-32" EngineError. Peak RSS grew by about 3 MiB for the DEFLATE file (nothing at all on a second open in the same process) and not at all for the BZIP2 one, against about 800 MiB each for the same two files with a plain `zf.read(info)`.
- Size limits. save and open_project share `_size_problem`, so badshop never writes a project it would then refuse. save raises "too big to open again" with a hint to export and start a new session. open's hint says badshop never saves a project that big. session.json has its own, smaller cap: through `json.loads` plus pydantic, 16 MiB of the worst-shaped JSON (`[{},{},...]`) peaked at 0.9 GB and 64 MiB peaked at 3.4 GB. The test meme's session.json is 7 KB, and a realistic long session stays under a few MB.
- Artifacts. Each listed artifact must hash to its id. `ArtifactStore.add` (Task 5) then decodes it only through `IMPORT_FORMATS` within `MAX_IMPORT_PIXELS` (so EPS is never reached), recomputes size, format and frames from the bytes, and turns any decoder failure into an EngineError, which open wraps as "damaged". `Session.__init__` makes `data.artifacts` the store's metas.
- Ids. Task 7's `_next_id` makes `s1, s2...` and `m1, m2...` (ASCII digits, no leading zero), and reads every step id, message id, message `step_ids` entry and artifact `produced_by` to find the next one. It calls `int()` on any suffix `isdigit()` accepts, so a hand-edited `"s²"` or a 5000-digit suffix would open and then make every later `propose()` and `add_message()` raise a bare ValueError. `_session_data` refuses, as damaged, any of those that doesn't `fullmatch` `STEP_ID` (`s[1-9][0-9]{0,8}`) or `MESSAGE_ID` (`m[1-9][0-9]{0,8}`). `fullmatch` also refuses a trailing new line, which a `$` anchor lets through. The message shows at most 16 characters of the id. Nine digits is far past any real session: `_next_id` hands out one past the highest number, so reaching ten digits takes a billion proposals, or a hand-edited `s999999999` (which opens) plus one more step; a project saved after that is refused on open with this same clean error. A deleted step's id that a message or an artifact still names is checked like any other, and still need not resolve to a step.
- Steps saved mid-turn. A `proposed` step becomes `rejected` (result_text `"rejected: badshop closed before it was approved"`, `finished_at` set, no error), the same way a stopped turn rejects what waits (`ApprovalGate.cancel_all`). That keeps a later replay, such as `auto_replay` after an edit, from running an agent step nobody approved: replay_from skips rejected steps. A step saved `approved` or `running` becomes `error` with "badshop closed before this step finished" and hint "replay the step to run it again", and its `result_text` comes from Task 7's `result_text`, like any failed step. Task 11's `build_messages` already answers the transcript's dangling tool calls.
- save writes both JSON members as ASCII (`ensure_ascii` left on). A lone surrogate, which a WebSocket JSON client can send in any text and pydantic keeps, is then an escape that reads back unchanged. With UTF-8 it raised UnicodeEncodeError, which Task 12's autosave handler (`EngineError, OSError`) would not catch, on every later save. The temp file is opened with `"xb"` under a random name, so the umask sets its mode (mkstemp's 0600 would stay on the project after `os.replace`). Saving over an existing project keeps that file's mode.
- The recipe rebuilds each included step's first output under its own name. A secondary output (prep's grid) is written next to it as `artifacts/<id>_grid.png`, so a later step that uses a secondary output reads the copy saved in the project.
- What save keeps is `session.referenced_ids()` (Task 8), so save itself has no rule of its own. Under ruling R6 that set also holds the pictures of a deleted step that a message's `step_ids` still names, and any picture whose short id is in the transcript. A reopened session then never lacks a picture the chat shows or the model may ask for by the id it was told. Their metas travel in `session.json` with `produced_by` unchanged, so `open_project` doesn't require that step id to resolve, and the reopened session's `referenced_ids()` gives the same set (`test_a_deleted_steps_picture_the_chat_still_points_at_is_saved_and_reopened`).
- `autosave` raises `EngineError` like `save`. The server (Task 12) catches and logs it, and does not fail the user's call.
- Restoring after a crash (spec §9, §10). Every autosave replaces `autosave/session.badshop`, so without help a new core's first change would overwrite what the last run left there before anyone could restore it. `claim_autosave()` moves that file to `autosave/previous.badshop` and returns its path. Task 12's `CoreApp.__init__` calls it once, before its session can change. The snapshot reports the result as `"restorable"`, and the user-only `session.restore {}` opens it with `path: None`, because the autosave is not the user's project file and Save must not write into it. Plan 4 only shows the offer. When there is nothing to move, a `previous.badshop` that no later run replaced is still returned. So a core that crashes again before its session changes, or before the shell restores it, still has the offer on the next launch. The core can't tell a crash from a quit, because `close()` autosaves too. It reports what the last run left either way, and Plan 4 decides how to word the offer. `claim_autosave` creates nothing and never raises, so it can't stop a core from starting. If the move fails, it returns None and the file stays in place for the next launch. A folder that refuses the rename usually refuses the autosave's temp file too, so this run's autosaves don't overwrite it.

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_project.py -q`
Expected: `100 passed` in about 7 seconds, offline (46 of them are the round trip: 23 tools, two variants each).
Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1203 passed, 1 deselected` (Task 8's 1103 plus these 100; the deselected one is the `network` test), and ruff prints `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add core/src/badshop/cli/argparse_gen.py core/src/badshop/session/project.py core/tests/test_project.py
git commit -m "feat(session): .badshop project files, CLI recipe export and autosave

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Tool worker process with wall-clock and memory limits, cancel and restart

**Files:**
- Create: `core/src/badshop/session/worker.py`
- Modify: `core/pyproject.toml` (adds `psutil>=6`) and `core/uv.lock`, both through `uv add`
- Test: `core/tests/test_worker.py`

**Interfaces:**
- Consumes:
  - Task 6 (`badshop.session.execution`): `ToolCall(tool: str, params: dict, inputs: dict[str, bytes], stem: str, trusted_urls: frozenset[str] = frozenset(), guard_network: bool = True)`;
    `ToolOutcome(ok: bool, outputs: list[OutputRecord] = [], lines: list[str] = [], data: dict = {}, error_message: str | None = None, error_hint: str | None = None, crashed: bool = False)`
    (a dataclass, so `==` compares fields); `OutputRecord.key`, `OutputRecord.data`; `execute_call(call: ToolCall) -> ToolOutcome`
    (an `EngineError`, including `registry.get`'s `unknown tool '<name>'`, gives `ok=False` with its message and hint; any other
    exception gives `crashed=True`, `"the tool crashed (<Type>: <message>)"`, hint `CRASH_HINT`);
    `CRASH_HINT = "this is a bug in badshop; other steps are unaffected"` (imported here, not redefined, so a worker crash
    and an exception inside `execute_call` always carry the same hint); `STOPPED = "stopped by the user"` (imported the
    same way: every executor's stopped outcome carries that message); `InProcessExecutor` (tests only).
    `WorkerExecutor` satisfies Task 6's `Executor` protocol structurally, `run(call, cancel=None)` included.
  - Task 4: `assets.PROGRESS: Callable[[str, int, int | None], None] | None` (`cached()` calls it after every chunk with
    `total` from Content-Length, so `total` is `None` for a response without one).
  - Task 4: `badshop.engine.cutout._SESSIONS: dict[str, object]` (model to rembg session; at most one entry) and
    `cutout.drop_sessions() -> None` (clears it; after a u2net cutout that gave back about 430 MB).
  - Plan 1: `badshop.tools.registry.ToolSpec`, `register`, `badshop.tools.REGISTRY`, `badshop.engine.types.Params`,
    `badshop.engine.result.EngineResult`, `badshop.engine.errors.EngineError`, the `prep` and `info` tools (`info`'s
    `data` is `{"width": w, "height": h}`).
- Produces (`badshop.session.worker`):
  - `class WorkerExecutor:` `__init__(self, timeout_s: float = 120.0, max_rss_mb: int = 3072, poll_s: float = 0.05)`;
    `run(call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome` (one caller at a time, others wait; never
    raises for anything a tool or the worker process does; `cancel` is that call's own stop signal, which may be set from
    any thread: already set when the call's turn comes, the call is never sent and the worker is left as it is; set
    while the call runs, including while a fresh worker starts for it, the worker is killed exactly as `cancel()` kills
    it); `cancel() -> None` and `close() -> None` (from any thread; `close` is idempotent); `__enter__` / `__exit__`
    (closes); read-only property `pid -> int | None` (the worker's pid, `None` while there is none). The public attributes
    `timeout_s`, `max_rss_mb` and `poll_s` are read on every call.
  - When the core itself is interrupted during a call (a `BaseException` such as `KeyboardInterrupt` raised by the core's
    `assets.PROGRESS` listener, or a `MemoryError` while unpickling an outcome), `run()` stops the worker and re-raises:
    that call's outcome may still be in the pipe, and the next call, on a fresh worker, must never read it.
  - Outcomes the executor makes itself (all `ok=False`, `outputs == []`). Every row but `run()` after `close()` and a call
    whose own `cancel` was set before it began ends the worker process, so the next call starts a fresh one; so does an `execute_call` outcome with `crashed=True` (a
    non-`EngineError` exception). An `EngineError` outcome keeps the same worker.

    | when | `error_message` | `error_hint` | `crashed` |
    |---|---|---|---|
    | wall clock | `the tool took longer than {timeout_s:g} s and was stopped` | `LIMIT_HINT` | False |
    | memory (RSS of the worker and its subprocesses) | `the tool used more than {max_rss_mb} MB of memory and was stopped` | `LIMIT_HINT` | False |
    | the worker process died (the pipe reads EOF, polling it raises `OSError`, or the process is gone) | `the tool's process died (exit code {N})` (N is negative for a signal on POSIX) | `CRASH_HINT` | True |
    | `cancel()` or `close()` during the call, or the call's own `cancel` event set during it | `stopped by the user` | None | False |
    | the call's own `cancel` event already set when `run()` gets to it (the call is not sent) | `stopped by the user` | None | False |
    | `run()` after `close()` | `the tool worker is closed` | None | False |
    | the worker did not say "ready" in time | `the tool worker did not start within {STARTUP_TIMEOUT_S:g} s` | `try again` | False |
    | creating the pipe or starting the process raised `OSError` (out of file descriptors, processes or memory) | `the tool worker could not start (<OSError>)` | `try again` | False |

  - Constants: `TEST_TOOLS_ENV = "BADSHOP_WORKER_TEST_TOOLS"`, `STARTUP_TIMEOUT_S = 60.0`, `CHILDREN_EVERY_S = 1.0`,
    `PROGRESS_EVERY_S = 0.1`, `STOP_WAIT_S = 5.0`, `LIMIT_HINT = "try smaller parameters or a smaller image"`;
    `CRASH_HINT` and `STOPPED` are importable from here too (Task 6's, imported).
  - Test hook, exactly: a worker process whose environment has `BADSHOP_WORKER_TEST_TOOLS=1` when it is spawned (tests
    `monkeypatch.setenv` it before the first `run`; the worker inherits the core's environment) calls
    `_register_test_tools()` before it reports ready, which registers, in that process only:
    `_sleep(seconds: float = 0, say: str = "")` (prints `say` to stdout, sleeps, returns `lines=["slept <seconds:g> s"]`,
    `data={"pid": <worker pid>}`), `_hog(mb: int, hold_s: float = 30)` (holds `mb` MB of touched memory),
    `_boom(engine: bool = False)` (raises `RuntimeError("boom")`, or `EngineError("boom", hint="a test error")`),
    `_die(code: int = 3, how: "exit" | "kill" = "exit")` (`os._exit(code)`, or kills itself with SIGKILL) and
    `_download(steps: int, every_s: float, sized: bool = True)` (calls `assets.PROGRESS("_download", i, steps if sized
    else None)` every `every_s`, as `cached()` does with and without a Content-Length) and `_sessions(put: bool = False)`
    (with `put`, caches a stand-in session under `"_test"` in the worker's `cutout._SESSIONS`; returns
    `data={"sessions": sorted(cutout._SESSIONS)}`). The core's own `REGISTRY` never has them.
  - Download progress: the worker sets its own `assets.PROGRESS` to forward `("progress", name, done, total)` over the pipe,
    at most every `PROGRESS_EVERY_S`, and always each download's last chunk: a chunk with `done == total` goes out at
    once, and a report the throttle held back goes out when another download starts or just before the call's outcome
    (so a response without a Content-Length still ends on its last chunk). The executor passes each one to the core's
    `assets.PROGRESS` (on the thread that called `run`) and moves the call's deadline to at least `timeout_s` from then.
  - Orphan guard: a worker exits by itself (`os._exit(1)`) as soon as the core process ends, however it ends.
  - Memory pressure between calls (ruling R8; carry-forward TRI T7 F3, "drop them under memory pressure"): the core sends
    each call over the pipe as `(call, max_rss_mb)`, with the limit it reads for that call. After the worker has sent the
    call's outcome and let go of the call and the outcome, it reads its own RSS (`psutil`; its subprocesses are not
    counted), and when that is above `max_rss_mb / 2` it calls `cutout.drop_sessions()`. The same worker goes on (a drop
    is not a restart); the next cutout rebuilds its session.

How it works (read before implementing):
- The worker is a `multiprocessing` **spawn** child (fork would copy the core's threads, event loop and sockets), started
  on the first `run` and reused. It imports every tool once (the module's own imports register the catalog), sends
  `"ready"`, then loops: receive a `(ToolCall, max_rss_mb)` pair, send `execute_call(call)`, then drop the cached rembg
  session if the worker holds more than half of `max_rss_mb` (see below); `None` or a closed pipe ends it. The deadline
  starts after "ready", so interpreter start and imports (about 0.3 s here, far more on a cold Windows disk) never count
  against a tool; they have their own `STARTUP_TIMEOUT_S`.
- While a call runs, the core polls the pipe every `poll_s`, then the process's liveness, the cancel `threading.Event`,
  the deadline, and the RSS of the worker plus its subprocesses (`psutil`). The worker's own RSS is read every poll (about
  10 µs); its subprocess list is refreshed every `CHILDREN_EVERY_S`, because psutil's `children(recursive=True)` scans every
  process on the machine (7 ms with 600 processes, which at 20 Hz would burn 14% of a core). No `RLIMIT_AS`
  (carry-forward SEC-S4: `import cv2` segfaults under a 4 GB `ulimit -v`).
- Poll and receive are one guarded read. On POSIX the pipe is a socketpair, and a dead worker's closed end polls as
  readable and then `recv` raises `EOFError`. On Windows it is a named pipe: `PipeConnection._poll` calls
  `_winapi.PeekNamedPipe`, which raises `BrokenPipeError` once the worker's end is closed. Both mean "the tool's process
  died". `test_a_pipe_that_breaks_while_polling_means_the_worker_died` emulates the Windows behaviour on POSIX, and on
  Windows the `[exit]` case meets the real thing.
- A kill takes the worker's own subprocesses too, reaps the process, closes the pipe and the `Process`
  (`test_restarts_do_not_leak_file_descriptors` guards a long-lived core that restarts workers many times). A call the
  core is interrupted in (any `BaseException` other than the internal `_Stopped`) also ends the worker before the
  exception propagates, so a stale outcome can never answer the next call.
- `cancel()` sets the executor's own event; `run()` clears it on entry, so a `cancel()` when nothing runs never stops a
  later call. The price is that `cancel()` can't reach a call that hasn't entered `run()` yet, so a caller that must stop
  one particular call (Task 11's Stop, which can land while the step is still on its way to the executor) passes that
  call's own `threading.Event` as `run(call, cancel)`: `run()` checks it once it holds the call lock and returns
  `STOPPED` without sending anything (or starting a worker) when it is set, and `_receive` polls it beside the
  executor's event, so setting it mid-call kills the worker the same way. It is never cleared, and it belongs to that one
  call, so it can't stop a later call or another caller's. `cancel()` stays for callers with no event: the server's
  shutdown (Task 13) and `CoreApp.close()` (Task 12). `close()` sets "closed" and the event under one lock, so no call
  can start after it; then it asks the idle worker to exit, and kills it after `STOP_WAIT_S`.
- The worker points fd 1 at fd 2: the core's stdout carries the server's handshake line (Task 13), so nothing a tool or a
  native library prints may land there. It ignores SIGINT (Ctrl-C in a terminal reaches the whole process group; the
  core stops the worker itself). It ignores Pillow's `DecompressionBombWarning` process-wide: the carry-forward notes that an
  89-179 Mpx image prints it before our own size checks refuse the image, and that silencing it with `catch_warnings` is not
  thread-safe, "so leave it to the worker" (one tool at a time runs there).
- The limits live in the core, so the worker watches it: before it says "ready", a daemon thread waits on
  `multiprocessing.parent_process().sentinel` and calls `os._exit(1)` when it fires. A core that crashes or is killed
  (spec §9 plans for core crashes and shell restarts; §5.7 kills the core on exit) therefore never leaves a worker running
  a tool with no wall-clock or memory limit, or overlapping the restarted core's own worker. On POSIX the sentinel is the
  read end of the pipe the core wrote the worker's start-up data into; the core holds the write end until it exits or
  calls `Process.close()`, which `_stop_worker` does only after the worker has exited. On Windows it is a handle to the
  core process.
- Tools that download assets (the first cutout fetches its 176 MB model; `text` fetches fonts) now do it in the worker, where
  the core's `assets.PROGRESS` listener does not exist and where the download would count against the wall clock (and a
  kill mid-download loses it). Forwarding progress keeps spec §5.1's "report progress through a callback, which the UI
  shows" working, and moving the deadline on each report means a slow connection cannot time out every first cutout.
  `cached()`'s own 60 s no-progress socket timeout still bounds a stalled download.
- Measured while writing this task (rembg 2.0.85, onnxruntime 1.30): the first u2net cutout of `lincoln.png` takes the
  worker to about 840-870 MB of RSS, and with its session cached the worker holds that afterwards; from the second
  cutout on it holds about 1120 MB (onnxruntime keeps its buffers at their peak). Dropping the session brings it back to
  about 470-500 MB. All of it is well under the 3072 MB default.
- Why the worker drops its rembg session above half its limit (ruling R8): Task 4's cached session is the one big thing
  the worker keeps between calls (at most one model; birefnet-general's weights are 5.5 times u2net's). Keeping it saves
  a rebuild on every cutout (0.3 to 0.6 s for u2net, more for the bigger models). But a worker that already holds more
  than half its limit leaves the next call less than half to work in, and the watchdog would then stop a step for
  memory that is only a cache. So after each call the worker reads its own RSS (about 10 µs) and drops the session
  above `max_rss_mb / 2`. The check runs after the outcome has gone out, so it never delays a step's result, and before
  the worker reads the next call. The call and its outcome are released first, so their images are not counted as
  memory the worker keeps. With the default 3072 MB (a 1536 MB line), the 840-1120 MB a worker holds after u2net
  cutouts keeps its session. A `tool_memory_mb` under about 2240 drops it after some cutouts (under about 1680, after
  every one), which costs a rebuild instead of a failed step. The core's `max_rss_mb` goes with every call because it
  is read on every call.
- For later tasks: Task 12 builds `WorkerExecutor(timeout_s=settings.tool_timeout_s, max_rss_mb=settings.tool_memory_mb)`,
  swaps in a new `WorkerExecutor` (and closes the old one) when `tool_timeout_s` or `tool_memory_mb` changes, and calls
  `close()` from `CoreApp.close()`; its `uv add` of psutil is then a no-op. Task 11: `cancel()` stops only a
  call that has entered `run()`, so the turn loop gives each executing step its own event (through Task 7's
  `Session.run(..., cancel=...)`) and sets that instead: a Stop that lands after `asyncio.to_thread` started
  `session.run` but before it reached the executor still stops the step, without running its tool. Because the worker is a spawn
  child, a script that creates a `WorkerExecutor` needs an `if __name__ == "__main__":` guard (`python -m badshop.server`
  and console scripts are fine, since multiprocessing does not re-import a package's `__main__`); Plan 6's frozen build
  must call `multiprocessing.freeze_support()` first thing in its entry point.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_worker.py`:
```python
"""The tool worker: wall-clock and memory limits, crashes, cancel, close (Task 10; review focus 5)."""

import hashlib
import io
import multiprocessing
import multiprocessing.connection
import os
import socket
import subprocess
import sys
import threading
import time

import psutil
import pytest
from PIL import Image

from badshop.engine import assets
from badshop.session import worker
from badshop.session.execution import InProcessExecutor, ToolCall
from badshop.session.worker import CRASH_HINT, LIMIT_HINT, TEST_TOOLS_ENV, WorkerExecutor
from badshop.tools import REGISTRY


@pytest.fixture
def test_tools(monkeypatch):
    monkeypatch.setenv(TEST_TOOLS_ENV, "1")  # read by each worker process when it starts


def call(tool: str, **params) -> ToolCall:
    return ToolCall(tool=tool, params=params, inputs={}, stem="")


def run_in_thread(w: WorkerExecutor, c: ToolCall) -> tuple[threading.Thread, list]:
    box: list = []
    t = threading.Thread(target=lambda: box.append(w.run(c)))
    t.start()
    return t, box


def assert_fresh_worker_works(w: WorkerExecutor, old_pid: int) -> None:
    out = w.run(call("_sleep"))
    assert out.ok and out.data["pid"] not in (old_pid, os.getpid())
    assert not psutil.pid_exists(old_pid)  # the old worker is gone, not left behind


def test_a_real_tool_gives_the_same_outcome_as_in_process():
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(buf, "PNG")
    data = buf.getvalue()
    aid = hashlib.sha256(data).hexdigest()
    c = ToolCall(tool="prep", params={"image": aid}, inputs={aid: data}, stem="pic")
    with WorkerExecutor() as w:
        out = w.run(c)
    assert out.ok and [o.key for o in out.outputs] == ["work", "grid"]
    with Image.open(io.BytesIO(out.outputs[0].data)) as im:
        assert im.size == (30, 20)
    assert out == InProcessExecutor().run(c)


def test_the_worker_starts_lazily_and_is_reused(test_tools):
    with WorkerExecutor() as w:
        assert w.pid is None
        a = w.run(call("_sleep"))
        b = w.run(call("_boom", engine=True))  # an EngineError is a normal failure: same worker
        c = w.run(call("_sleep"))
        assert a.ok and a.lines == ["slept 0 s"] and a.data["pid"] == w.pid != os.getpid()
        assert (b.ok, b.crashed, b.error_message, b.error_hint) == (False, False, "boom", "a test error")
        assert c.ok and c.data["pid"] == a.data["pid"]


def test_the_worker_drops_cached_rembg_sessions_under_memory_pressure(test_tools):
    with WorkerExecutor() as w:
        assert w.run(call("_sessions", put=True)).data["sessions"] == ["_test"]
        pid = w.pid
        assert w.run(call("_sessions")).data["sessions"] == ["_test"]  # kept: far below half of 3072 MB
        held_mb = psutil.Process(pid).memory_info().rss / 2**20
        # A tiny limit: the worker stays under it (the watchdog lets calls run) but holds more than half of it
        w.max_rss_mb = int(held_mb * 1.5)
        assert w.run(call("_sessions")).data["sessions"] == ["_test"]  # dropped after the call, not during it
        out = w.run(call("_sessions"))
        assert out.ok and out.data["sessions"] == [] and w.pid == pid  # the same worker: a drop is not a restart


FAILURES = [
    pytest.param("_sleep", {"seconds": 60}, {"timeout_s": 1.0},
                 "the tool took longer than 1 s and was stopped", LIMIT_HINT, False, id="hang"),
    pytest.param("_hog", {"mb": 800}, {"max_rss_mb": 400},
                 "the tool used more than 400 MB of memory and was stopped", LIMIT_HINT, False, id="memory"),
    pytest.param("_boom", {}, {}, "the tool crashed (RuntimeError: boom)", CRASH_HINT, True, id="exception"),
    pytest.param("_die", {"code": 3}, {}, "the tool's process died (exit code 3)", CRASH_HINT, True,
                 id="exit"),
    pytest.param("_die", {"how": "kill"}, {}, "the tool's process died (exit code -9)", CRASH_HINT, True,
                 id="killed", marks=pytest.mark.skipif(os.name != "posix", reason="POSIX signal exit code")),
]


@pytest.mark.parametrize("tool, params, limits, message, hint, crashed", FAILURES)
def test_a_failing_tool_fails_cleanly_and_the_next_call_gets_a_fresh_worker(
        test_tools, tool, params, limits, message, hint, crashed):
    with WorkerExecutor(**{"timeout_s": 20.0, **limits}) as w:
        first = w.run(call("_sleep")).data["pid"]
        t = time.monotonic()
        out = w.run(call(tool, **params))
        assert time.monotonic() - t < 15  # well short of the 60 s sleep and the 20 s default here
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (False, message, hint, crashed)
        assert out.outputs == [] and w.pid is None
        assert_fresh_worker_works(w, first)


def test_cancel_stops_the_running_call_and_is_a_no_op_when_idle(test_tools):
    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        w.cancel()  # nothing is running: the next call is not affected
        assert w.run(call("_sleep")).data["pid"] == first
        t, box = run_in_thread(w, call("_sleep", seconds=60))
        start = time.monotonic()
        while t.is_alive() and time.monotonic() - start < 10:
            w.cancel()  # a no-op until the call is running
            t.join(0.05)
        assert not t.is_alive()
        assert (box[0].ok, box[0].error_message, box[0].error_hint) == (False, "stopped by the user", None)
        assert_fresh_worker_works(w, first)


def test_a_call_whose_own_cancel_event_is_set_before_it_begins_is_never_sent(test_tools):
    stop = threading.Event()
    stop.set()  # Task 11's Stop landed while the step was still on its way to the executor
    with WorkerExecutor() as w:
        out = w.run(call("_sleep"), stop)
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (
            False, "stopped by the user", None, False)
        assert w.pid is None  # nothing to send, so no worker was started for it
        first = w.run(call("_sleep")).data["pid"]
        out = w.run(call("_die"), cancel=stop)  # had it been sent, the worker would have died
        assert out.error_message == "stopped by the user" and w.pid == first
        assert w.run(call("_sleep")).data["pid"] == first  # the same worker, untouched


def test_a_call_whose_own_cancel_event_is_set_while_it_runs_is_stopped(test_tools, monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(assets, "PROGRESS", lambda *event: stop.set())  # the tool is under way: stop it
    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        t = time.monotonic()
        out = w.run(call("_download", steps=1000, every_s=0.05), cancel=stop)  # 50 s if nothing stops it
        assert time.monotonic() - t < 15
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (
            False, "stopped by the user", None, False)
        assert out.outputs == [] and w.pid is None  # killed, exactly as cancel() kills it
        assert_fresh_worker_works(w, first)


def test_close_stops_the_worker_and_later_calls_fail_cleanly(test_tools):
    with WorkerExecutor() as w:  # leaving the block closes it a second time, which is fine
        pid = w.run(call("_sleep")).data["pid"]
        w.close()
        assert w.pid is None and not psutil.pid_exists(pid)
        out = w.run(call("_sleep"))
        assert (out.ok, out.error_message) == (False, "the tool worker is closed")


def test_close_stops_a_running_call(test_tools):
    with WorkerExecutor() as w:
        pid = w.run(call("_sleep")).data["pid"]
        t, box = run_in_thread(w, call("_sleep", seconds=60))
        w.close()
        t.join(10)
        assert not t.is_alive()
        # close() either stopped the call or got in before it started
        assert not box[0].ok and box[0].error_message in ("stopped by the user", "the tool worker is closed")
        assert not psutil.pid_exists(pid)


def test_a_worker_that_does_not_start_in_time_fails_cleanly(test_tools, monkeypatch):
    with WorkerExecutor(poll_s=0.001) as w:  # no Python process is ready 1 ms after it is spawned
        with monkeypatch.context() as m:
            m.setattr(worker, "STARTUP_TIMEOUT_S", 0.0)
            out = w.run(call("_sleep"))
        assert (out.ok, out.error_message, out.error_hint) == (
            False, "the tool worker did not start within 0 s", "try again")
        assert w.pid is None and w.run(call("_sleep")).ok


@pytest.mark.parametrize("step, errno, text", [
    ("pipe", 24, "Too many open files"),  # EMFILE: no file descriptors left for the pipe
    ("process", 11, "out of processes"),  # EAGAIN from fork/exec
])
def test_a_worker_that_cannot_be_spawned_fails_cleanly(test_tools, monkeypatch, step, errno, text):
    def refuse(*args):
        raise OSError(errno, text)

    ctx = multiprocessing.get_context("spawn")
    with WorkerExecutor() as w:
        with monkeypatch.context() as m:
            if step == "pipe":
                m.setattr(type(ctx), "Pipe", refuse)
            else:
                m.setattr(ctx.Process, "start", refuse)
            out = w.run(call("_sleep"))
        assert (out.ok, out.error_hint) == (False, "try again")
        assert out.error_message == f"the tool worker could not start ([Errno {errno}] {text})"
        assert w.pid is None and w.run(call("_sleep")).ok


def test_download_progress_reaches_the_core_and_does_not_count_against_the_clock(test_tools, monkeypatch):
    events = []
    monkeypatch.setattr(assets, "PROGRESS", lambda *a: events.append(a))
    with WorkerExecutor(timeout_s=1.5) as w:
        slow = w.run(call("_download", steps=6, every_s=0.3))  # 1.8 s in all, but progress every 0.3 s
        assert slow.ok and events == [("_download", i, 6) for i in range(1, 7)]
        events.clear()
        fast = w.run(call("_download", steps=50, every_s=0.001))  # forwarded at most every 0.1 s
        assert fast.ok and events[-1] == ("_download", 50, 50) and len(events) < 50
        events.clear()
        unsized = w.run(call("_download", steps=50, every_s=0.001, sized=False))  # no Content-Length
        assert unsized.ok and events[-1] == ("_download", 50, None) and len(events) < 50


def test_held_back_progress_goes_out_before_the_next_download_and_at_the_end(monkeypatch):
    monkeypatch.setattr(worker, "PROGRESS_EVERY_S", 3600.0)  # the throttle holds back every report
    core_end, worker_end = multiprocessing.Pipe()
    with core_end, worker_end:
        sender = worker._Sender(worker_end)
        for name, total in (("fonts/a.ttf", None), ("fonts/b.ttf", None), ("model.onnx", 3)):
            for done in (1, 2, 3):
                sender.progress(name, done, total)
        sender.flush()  # the worker flushes before it sends a call's outcome
        heard = []
        while core_end.poll():
            heard.append(core_end.recv())
    assert heard == [("progress", "fonts/a.ttf", 3, None), ("progress", "fonts/b.ttf", 3, None),
                     ("progress", "model.onnx", 3, 3)]


def test_a_call_interrupted_in_the_core_leaves_nothing_for_the_next_call(test_tools, monkeypatch):
    class Interrupted(BaseException):  # like KeyboardInterrupt, without its special handling in pytest
        pass

    def listener(*event):
        raise Interrupted

    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        with monkeypatch.context() as m:
            m.setattr(assets, "PROGRESS", listener)
            with pytest.raises(Interrupted):
                w.run(call("_download", steps=3, every_s=0))
        assert w.pid is None  # the unread "downloaded 3 chunks" outcome went with the worker
        assert w.run(call("_sleep")).lines == ["slept 0 s"]
        assert_fresh_worker_works(w, first)


@pytest.mark.skipif(os.name != "posix", reason="emulates a Windows pipe on a POSIX socketpair")
def test_a_pipe_that_breaks_while_polling_means_the_worker_died(test_tools, monkeypatch):
    # On Windows, polling a pipe whose other end has closed raises BrokenPipeError instead of reporting
    # EOF (the [exit] case above meets the real thing there). Emulate that here.
    real_poll = multiprocessing.connection.Connection.poll

    def windows_poll(conn, timeout=0.0):
        if not real_poll(conn, timeout):
            return False
        with socket.socket(fileno=os.dup(conn.fileno())) as s:
            if s.recv(1, socket.MSG_PEEK) == b"":  # EOF: the worker's end is closed
                raise BrokenPipeError(32, "The pipe has been ended")
        return True

    with WorkerExecutor() as w:
        first = w.run(call("_sleep")).data["pid"]
        monkeypatch.setattr(multiprocessing.connection.Connection, "poll", windows_poll)
        out = w.run(call("_die"))
        assert (out.ok, out.error_message, out.error_hint, out.crashed) == (
            False, "the tool's process died (exit code 3)", CRASH_HINT, True)
        assert_fresh_worker_works(w, first)


CORE_SCRIPT = """\
from badshop.session.execution import ToolCall
from badshop.session.worker import WorkerExecutor

if __name__ == "__main__":
    w = WorkerExecutor()
    print(w.run(ToolCall(tool="_sleep", params={}, inputs={}, stem="")).data["pid"], flush=True)
    w.run(ToolCall(tool="_sleep", params={"seconds": 60}, inputs={}, stem=""))
"""


def test_a_worker_whose_core_dies_exits_too(test_tools, tmp_path):
    script = tmp_path / "core.py"
    script.write_text(CORE_SCRIPT)
    with subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True) as core:
        worker_process = psutil.Process(int(core.stdout.readline()))
        core.kill()  # mid-call, the way a crash or the shell ends the core
    try:
        worker_process.wait(timeout=10)  # psutil.TimeoutExpired if the worker outlives its core
    finally:
        if worker_process.is_running():
            worker_process.kill()


def test_what_a_tool_prints_goes_to_stderr_not_the_cores_stdout(test_tools, capfd):
    with WorkerExecutor() as w:
        assert w.run(call("_sleep", say="noise from a tool")).ok
    out, err = capfd.readouterr()
    assert "noise from a tool" not in out and "noise from a tool" in err


def test_pillows_size_warning_stays_out_of_the_log(capfd):
    buf = io.BytesIO()
    Image.new("1", (10000, 9000)).save(buf, "PNG")  # 90 Mpx, past Pillow's warning line; a few KB as PNG
    data = buf.getvalue()
    aid = hashlib.sha256(data).hexdigest()
    with WorkerExecutor() as w:
        out = w.run(ToolCall(tool="info", params={"image": aid}, inputs={aid: data}, stem="big"))
    assert out.ok and out.data == {"width": 10000, "height": 9000}  # the image really was opened
    assert "DecompressionBombWarning" not in capfd.readouterr().err


def test_the_test_tools_need_the_env_var(monkeypatch):
    monkeypatch.delenv(TEST_TOOLS_ENV, raising=False)
    test_only = {"_sleep", "_hog", "_boom", "_die", "_download", "_sessions"}
    assert not test_only & set(REGISTRY)  # the core never has them
    with WorkerExecutor() as w:
        out = w.run(call("_die"))
    assert (out.ok, out.crashed, out.error_message) == (False, False, "unknown tool '_die'")


@pytest.mark.skipif(not hasattr(psutil.Process, "num_fds"), reason="counts POSIX file descriptors")
def test_restarts_do_not_leak_file_descriptors(test_tools):
    me = psutil.Process()
    with WorkerExecutor() as w:
        assert w.run(call("_sleep")).ok  # the first spawn may open lasting helpers (the resource tracker)
        before = me.num_fds()
        for _ in range(3):
            assert w.run(call("_die")).crashed
            assert w.run(call("_sleep")).ok
        assert me.num_fds() == before
```

Review focus 5 is `test_a_failing_tool_fails_cleanly_and_the_next_call_gets_a_fresh_worker`: a hanging tool, a tool past
the memory limit, a non-`EngineError` exception, an `os._exit` and a SIGKILL each fail with a clean message and hint, and
the very next call succeeds on a new worker process while the old one is gone. The same holds when polling the pipe
itself raises, as it does on Windows (`test_a_pipe_that_breaks_while_polling_means_the_worker_died`), and when the core
is interrupted mid-call (`test_a_call_interrupted_in_the_core_leaves_nothing_for_the_next_call`).
Ruling R8 (drop cached rembg sessions under memory pressure) is
`test_the_worker_drops_cached_rembg_sessions_under_memory_pressure`. A call's own cancel event (Task 11's Stop) is
`test_a_call_whose_own_cancel_event_is_set_before_it_begins_is_never_sent` (no worker is started for it, and a `_die`
call that would have ended the running worker leaves it untouched) and
`test_a_call_whose_own_cancel_event_is_set_while_it_runs_is_stopped` (the core's progress listener sets it once the tool
is under way: the worker is killed and the next call gets a fresh one).

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_worker.py -q`
Expected: a collection error, `ModuleNotFoundError: No module named 'psutil'` (it arrives in Step 3; were psutil already
installed, the error would be `ImportError: cannot import name 'worker' from 'badshop.session'`).

- [ ] **Step 3: Add psutil**

Run: `cd core && uv add 'psutil>=6'`

This rewrites the dependency list in `core/pyproject.toml` from
```toml
    "pydantic>=2.7,<3",
    "platformdirs>=4",
]
```
to
```toml
    "pydantic>=2.7,<3",
    "platformdirs>=4",
    "psutil>=6",
]
```
and locks psutil in `core/uv.lock` (7.2.2 when this plan was written). Task 12's later
`uv add "websockets>=15,<17" "psutil>=6"` leaves this line as it is (a no-op for psutil) and appends
`"websockets>=15,<17"` after it.

- [ ] **Step 4: Implement the worker**

`core/src/badshop/session/worker.py`:
```python
"""Tool calls in a worker process, with a wall-clock limit, a memory limit, cancel and restart.

A runaway loop, a memory blow-up or a native crash in a tool takes down only the worker: the step fails
with a clean error and the next call starts a fresh worker (carry-forward SEC-S4; spec §5.4's "cancel at
the next safe point"). The memory limit is an RSS watchdog, not RLIMIT_AS (under a 4 GB `ulimit -v`,
`import cv2` segfaults), so it works the same way on Linux, macOS and Windows. The limits live in the
core, so a worker whose core has died exits on its own.

Asset downloads inside a tool (the first cutout fetches its model) report progress to the core's
`assets.PROGRESS` through the pipe, and each report pushes the deadline back to a full `timeout_s`:
downloading is not the tool's time, and a slow connection must not kill every first cutout.

Between calls, a worker that holds more than half of the memory limit drops its cached rembg session
(carry-forward TRI T7 F3), so a cache never leaves the next call too little room.

A call can carry its own stop signal (`run(call, cancel)`, the agent's Stop): set before the call
begins, it is never sent; set while it runs, the worker is killed, as `cancel()` kills it.

The worker is a `spawn` child: a script that creates a WorkerExecutor needs an
`if __name__ == "__main__":` guard (`python -m badshop.server` and console scripts are fine), and a
frozen build must call `multiprocessing.freeze_support()` first.
"""

import multiprocessing
import multiprocessing.connection
import os
import signal
import threading
import time
import warnings
from typing import Literal, NoReturn

import psutil
from PIL import Image
from pydantic import Field

from badshop.engine import assets, cutout
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params
from badshop.session.execution import CRASH_HINT, STOPPED, ToolCall, ToolOutcome, execute_call
from badshop.tools.registry import ToolSpec, register  # importing badshop.tools registers every tool

TEST_TOOLS_ENV = "BADSHOP_WORKER_TEST_TOOLS"  # "1": the worker also registers the test tools below
STARTUP_TIMEOUT_S = 60.0  # spawning Python and importing the tools; not counted against the tool
CHILDREN_EVERY_S = 1.0  # listing the worker's own subprocesses scans every process, so do it sparingly
PROGRESS_EVERY_S = 0.1  # the worker forwards download progress at most this often, plus the last chunk
STOP_WAIT_S = 5.0
LIMIT_HINT = "try smaller parameters or a smaller image"


def _failed(message: str, hint: str | None = None, crashed: bool = False) -> ToolOutcome:
    return ToolOutcome(ok=False, error_message=message, error_hint=hint, crashed=crashed)


def _report_progress(name: str, done: int, total: int | None) -> None:
    listener = assets.PROGRESS
    if listener is not None:
        try:
            listener(name, done, total)
        except Exception:  # a broken listener (say, the server shutting down) must not fail the tool
            pass


class _Stopped(Exception):
    """The worker was stopped or died; `outcome` is what the caller gets."""

    def __init__(self, outcome: ToolOutcome):
        super().__init__(outcome.error_message)
        self.outcome = outcome


class WorkerExecutor:
    """Runs ToolCalls in one reusable worker process, spawned on the first call.

    `run` serves one caller at a time (others wait); `cancel` and `close` may be called from any thread,
    and so may a call's own cancel event be set. `timeout_s`, `max_rss_mb` and `poll_s` are read on
    every call."""

    def __init__(self, timeout_s: float = 120.0, max_rss_mb: int = 3072, poll_s: float = 0.05):
        self.timeout_s = timeout_s
        self.max_rss_mb = max_rss_mb
        self.poll_s = poll_s
        self._ctx = multiprocessing.get_context("spawn")  # fork would copy the core's threads and sockets
        self._proc = None
        self._conn = None
        self._pid: int | None = None
        self._ps: psutil.Process | None = None
        self._kids: list[psutil.Process] = []
        self._kids_at = 0.0
        self._call_lock = threading.Lock()  # one run at a time
        self._state = threading.Lock()  # makes close() atomic with run()'s closed check and cancel reset
        self._closed = False
        self._cancel = threading.Event()

    @property
    def pid(self) -> int | None:
        """The worker's process id, or None while there is no worker."""
        return self._pid

    def run(self, call: ToolCall, cancel: threading.Event | None = None) -> ToolOutcome:
        """Run one call in the worker. `cancel` is this call's own stop signal: already set when the call's
        turn comes, the call is never sent and the worker is left as it is; set while it runs, the worker
        is killed, as for cancel(). Either way the outcome says "stopped by the user"."""
        with self._call_lock:
            with self._state:
                if self._closed:
                    return _failed("the tool worker is closed")
                self._cancel.clear()  # a cancel() from before this call is not for it
            if cancel is not None and cancel.is_set():  # stopped before it began: the tool never runs
                return _failed(STOPPED)
            return self._run(call, cancel)

    def cancel(self) -> None:
        """Stop the running call; its outcome says "stopped by the user". Does nothing when idle, so it
        can't reach a call that hasn't entered run() yet: a caller that must stop one particular call
        passes that call's own event to run()."""
        self._cancel.set()

    def close(self) -> None:
        """Stop any running call and the worker. Later calls fail with "the tool worker is closed"."""
        with self._state:
            self._closed = True
            self._cancel.set()
        with self._call_lock:
            self._stop_worker(graceful=True)

    def __enter__(self) -> "WorkerExecutor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _run(self, call: ToolCall, cancel: threading.Event | None) -> ToolOutcome:
        try:
            if self._proc is None or not self._proc.is_alive():
                self._start(cancel)
            try:
                self._conn.send((call, self.max_rss_mb))  # the worker drops cached models above half of it
            except OSError:  # the worker died between calls
                self._died()
            outcome = self._receive(time.monotonic() + self.timeout_s, _failed(
                f"the tool took longer than {self.timeout_s:g} s and was stopped", LIMIT_HINT), cancel)
        except _Stopped as s:
            return s.outcome
        except BaseException:
            # Interrupted in the core (a progress listener raised KeyboardInterrupt, unpickling ran out of
            # memory): this call's outcome may still be on its way, and the next call must not read it.
            self._stop_worker()
            raise
        if outcome.crashed:  # an exception other than EngineError: don't trust this process again
            self._stop_worker()
        return outcome

    def _start(self, cancel: threading.Event | None) -> None:
        self._stop_worker()  # release a worker that died between calls
        parent = child = None
        try:
            parent, child = self._ctx.Pipe()
            proc = self._ctx.Process(target=_worker_main, args=(child,), name="badshop-worker", daemon=True)
            proc.start()
        except OSError as e:  # out of file descriptors, processes or memory
            if parent is not None:
                parent.close()
            raise _Stopped(_failed(f"the tool worker could not start ({e})", "try again")) from None
        finally:
            if child is not None:
                child.close()  # the worker holds the only other end, so its death reads as EOF here
        self._proc, self._conn, self._pid = proc, parent, proc.pid
        try:
            self._ps = psutil.Process(proc.pid)
        except psutil.Error:  # already gone: _receive reports how it died
            self._ps = None
        self._kids, self._kids_at = [], time.monotonic()
        self._receive(time.monotonic() + STARTUP_TIMEOUT_S,
                      _failed(f"the tool worker did not start within {STARTUP_TIMEOUT_S:g} s", "try again"),
                      cancel)

    def _receive(self, deadline: float, late: ToolOutcome, cancel: threading.Event | None):
        """The worker's next message other than download progress, which goes to assets.PROGRESS and
        moves the deadline. On cancel() or the call's own `cancel` event, the deadline, the memory limit
        or the worker's death, the worker is stopped and _Stopped carries the outcome."""
        while True:
            try:
                ready = self._conn.poll(self.poll_s)
                message = self._conn.recv() if ready else None
            except (EOFError, OSError):  # the worker's end closed (on Windows, poll itself raises)
                self._died()
            if ready:
                if not (isinstance(message, tuple) and message[:1] == ("progress",)):
                    return message
                _report_progress(*message[1:])
                deadline = max(deadline, time.monotonic() + self.timeout_s)
            elif not self._proc.is_alive():
                self._died()
            if self._cancel.is_set() or (cancel is not None and cancel.is_set()):
                self._kill(_failed(STOPPED))
            if time.monotonic() >= deadline:
                self._kill(late)
            if self._rss_mb() > self.max_rss_mb:
                self._kill(_failed(f"the tool used more than {self.max_rss_mb} MB of memory and was stopped",
                                   LIMIT_HINT))

    def _rss_mb(self) -> float:
        """Resident memory of the worker and its own subprocesses, in MB."""
        if self._ps is None:
            return 0.0
        now = time.monotonic()
        if now - self._kids_at >= CHILDREN_EVERY_S:
            try:
                self._kids = self._ps.children(recursive=True)
            except psutil.Error:
                self._kids = []
            self._kids_at = now
        total = 0
        for p in (self._ps, *self._kids):
            try:
                total += p.memory_info().rss
            except psutil.Error:  # exited since the last listing
                pass
        return total / 2**20

    def _died(self) -> NoReturn:
        self._proc.join(STOP_WAIT_S)  # the pipe can close a moment before the exit status is ready
        code = self._stop_worker()
        raise _Stopped(_failed(f"the tool's process died (exit code {code})", CRASH_HINT, crashed=True))

    def _kill(self, outcome: ToolOutcome) -> NoReturn:
        self._stop_worker()
        raise _Stopped(outcome)

    def _stop_worker(self, graceful: bool = False) -> int | None:
        """End the worker (asking it to exit first when graceful), release it, return its exit code."""
        proc, conn, ps = self._proc, self._conn, self._ps
        self._proc = self._conn = self._ps = self._pid = None
        self._kids = []
        if proc is None:
            return None
        if graceful and proc.is_alive():
            try:
                conn.send(None)
                proc.join(STOP_WAIT_S)
            except OSError:
                pass
        if proc.is_alive():
            try:
                kids = ps.children(recursive=True) if ps is not None else []
            except psutil.Error:
                kids = []
            for k in kids:
                try:
                    k.kill()
                except psutil.Error:
                    pass
            proc.kill()
            proc.join(STOP_WAIT_S)
        code = proc.exitcode
        conn.close()
        if code is not None:  # Process.close() refuses a process that is somehow still running
            proc.close()
        return code


class _Sender:
    """The worker's end of the pipe: one lock for every message, and throttled download progress.

    A report the throttle holds back is sent when another download starts or by flush(), which runs
    before each call's outcome, so the core always hears a download's last chunk (even when the size
    is unknown, so no chunk has done == total)."""

    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.Lock()
        self.last = time.monotonic()  # when a progress report was last sent
        self.held: tuple | None = None  # the latest report the throttle held back

    def __call__(self, message) -> None:
        with self.lock:
            self.conn.send(message)

    def progress(self, name: str, done: int, total: int | None) -> None:
        message = ("progress", name, done, total)
        with self.lock:
            if self.held is not None and self.held[1] != name:  # another download: finish the last one
                self.conn.send(self.held)
            self.held = message
            now = time.monotonic()
            if done == total or now - self.last >= PROGRESS_EVERY_S:
                self.conn.send(message)
                self.last, self.held = now, None

    def flush(self) -> None:
        with self.lock:
            if self.held is not None:
                self.conn.send(self.held)
                self.held = None


def _exit_with_the_core(core_sentinel) -> None:
    """Runs on a daemon thread in the worker. The time and memory limits live in the core, so when the
    core ends (a crash, the shell killing it) the worker must not keep running a tool unwatched, or
    overlap with the worker of a restarted core. The sentinel becomes ready when the core exits, on
    POSIX and on Windows."""
    multiprocessing.connection.wait([core_sentinel])
    os._exit(1)


def _drop_sessions_under_pressure(me: psutil.Process, max_rss_mb: float) -> None:
    """Runs in the worker after each call (carry-forward TRI T7 F3: drop cached sessions under memory
    pressure). The cached rembg session is the one big thing the worker keeps between calls; once the
    worker holds more than half of the core's limit, the next call would have less than half to work in,
    so free the session and let the next cutout rebuild it (0.3 to 0.6 s for u2net)."""
    try:
        held_mb = me.memory_info().rss / 2**20
    except psutil.Error:
        return
    if held_mb > max_rss_mb / 2:
        cutout.drop_sessions()


def _worker_main(conn) -> None:
    """The worker process. The tools are already imported (this module's imports); run calls until told
    to stop or until the core goes away."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl-C in a terminal reaches us too; the core stops us
    try:
        os.dup2(2, 1)  # the core's stdout carries its handshake line: whatever a tool prints goes to stderr
    except OSError:
        pass
    # Pillow warns about 89-179 Mpx images before our own size checks refuse them (carry-forward);
    # one tool at a time runs here, so a process-wide filter is safe where catch_warnings is not.
    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
    core = multiprocessing.parent_process()
    if core is not None:  # always, in a spawned worker
        threading.Thread(target=_exit_with_the_core, args=(core.sentinel,), name="badshop-core-watch",
                         daemon=True).start()
    send = _Sender(conn)
    assets.PROGRESS = send.progress  # downloads inside a tool report to the core's listener
    if os.environ.get(TEST_TOOLS_ENV) == "1":
        _register_test_tools()
    me = psutil.Process()
    send("ready")
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            return
        if message is None:
            return
        call, max_rss_mb = message  # the core's memory limit, as it read it for this call
        outcome = execute_call(call)
        send.flush()
        send(outcome)
        del message, call, outcome  # count what the worker keeps between calls, not this call's images
        _drop_sessions_under_pressure(me, max_rss_mb)


# Test-only tools: they misbehave on purpose. Only a worker whose environment has
# BADSHOP_WORKER_TEST_TOOLS=1 registers them; the core's own registry never has them.

class _SleepParams(Params):
    seconds: float = Field(0.0, ge=0, le=3600)
    say: str = Field("", max_length=200, description="printed to stdout before sleeping")


class _HogParams(Params):
    mb: int = Field(ge=1, le=65536)
    hold_s: float = Field(30.0, ge=0, le=3600)


class _BoomParams(Params):
    engine: bool = False  # raise EngineError instead of RuntimeError


class _DieParams(Params):
    code: int = Field(3, ge=0, le=255)
    how: Literal["exit", "kill"] = "exit"  # os._exit(code), or kill the process with a signal


class _DownloadParams(Params):
    steps: int = Field(ge=1, le=10000)
    every_s: float = Field(ge=0, le=60)
    sized: bool = True  # report the total, as cached() does when the response has a Content-Length


class _SessionsParams(Params):
    put: bool = False  # cache a stand-in rembg session first


def _sleep(p: _SleepParams, store) -> EngineResult:
    if p.say:
        print(p.say, flush=True)
    time.sleep(p.seconds)
    return EngineResult(lines=[f"slept {p.seconds:g} s"], data={"pid": os.getpid()})


def _hog(p: _HogParams, store) -> EngineResult:
    block = b"x" * (p.mb * 2**20)  # filled, so every page is really resident
    time.sleep(p.hold_s)
    return EngineResult(lines=[f"held {len(block) // 2**20} MB"])


def _boom(p: _BoomParams, store) -> EngineResult:
    if p.engine:
        raise EngineError("boom", hint="a test error")
    raise RuntimeError("boom")


def _die(p: _DieParams, store) -> EngineResult:
    if p.how == "kill":
        os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
    os._exit(p.code)


def _download(p: _DownloadParams, store) -> EngineResult:
    """Reports progress the way assets.cached does, without the network."""
    for i in range(1, p.steps + 1):
        time.sleep(p.every_s)
        if assets.PROGRESS is not None:
            assets.PROGRESS("_download", i, p.steps if p.sized else None)
    return EngineResult(lines=[f"downloaded {p.steps} chunks"])


def _sessions(p: _SessionsParams, store) -> EngineResult:
    """The worker's cached rembg sessions, by model (with put, after caching a stand-in one)."""
    if p.put:
        cutout._SESSIONS["_test"] = object()
    return EngineResult(data={"sessions": sorted(cutout._SESSIONS)})


def _register_test_tools() -> None:
    for name, params, fn in (("_sleep", _SleepParams, _sleep), ("_hog", _HogParams, _hog),
                             ("_boom", _BoomParams, _boom), ("_die", _DieParams, _die),
                             ("_download", _DownloadParams, _download),
                             ("_sessions", _SessionsParams, _sessions)):
        register(ToolSpec(name=name, params=params, run=fn, summary=f"worker test tool {name}",
                          description="Misbehaves on purpose for tests/test_worker.py.", category="test",
                          mutates=False, read_only=True))
```

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_worker.py -v`
Expected: 25 passed in about 11 s (on Windows the `killed` case, the pipe emulation and the file-descriptor test are
skipped).

Then the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1228 passed, 1 deselected` in about a minute and a half (Task 9's 1203 plus these 25; the deselected one is
the `network` test), and ruff prints `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add core/pyproject.toml core/uv.lock core/src/badshop/session/worker.py core/tests/test_worker.py
git commit -m "feat(session): tool worker process with time and memory limits, cancel and restart

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Agent: provider protocol, scripted fake provider, approval gate, context, turn loop

**Files:**
- Create: `core/src/badshop/agent/__init__.py`, `core/src/badshop/agent/provider.py`, `core/src/badshop/agent/fake.py`, `core/src/badshop/agent/approval.py`, `core/src/badshop/agent/context.py`, `core/src/badshop/agent/loop.py`
- Test: `core/tests/test_agent.py`

No existing file changes: the agent only drives the session through its public methods (spec §5: every tool call goes through `session/`).

**Interfaces:**
- Consumes:
  - Plan 1: `badshop.tools.REGISTRY` (importing `badshop.tools` registers every tool); `registry.get(name) -> ToolSpec` (EngineError `unknown tool 'x'` with the tool list as hint); `registry.image_fields(params_cls) -> dict[str, bool]` (image-ref field -> is a list); `ToolSpec.name`, `.description`, `.read_only`; `EngineError(message, hint)`.
  - Task 2: `registry.llm_schema(spec) -> dict` (user-only fields removed); `runner.validate(name: str, raw: dict, actor: str = "user") -> Params` (EngineError `bad parameters for <name>` / `<name>: <field> can only be set by the user`); `runner.explain(e: ValidationError) -> str`; `registry.get("export").writes_files is True` and `read_only is False`.
  - Task 5: `session.models.Step`, `Part(type, text=None, artifact_id=None)`, `ArtifactMeta` (`id, label, width, height`); `session.artifacts.short(id) -> str`; `ArtifactStore.meta: dict[str, ArtifactMeta]` and `ArtifactStore.resolve(ref) -> str` (EngineError `no such artifact: <ref>`, never touches the disk, snapshots its keys, so it is safe to call from the event loop while a session call runs in a thread); `ArtifactStore.import_image` labels the working copy `<name>_work` (so the tests' Lincoln is `lincoln_work`).
  - Task 6: `session.execution.ToolOutcome` (the tests' held executor returns one); `execute_call` (the tests patch it to see whether a tool really ran); `InProcessExecutor` (`run(call, cancel=None)` runs the tool here unless `cancel` is already set, which gives `ok=False`, `error_message="stopped by the user"`; `cancel`/`close` are no-ops; a test subclass counts cancels); the `Executor` protocol's `run(call, cancel: threading.Event | None = None) / cancel() / close()` (the event is that one call's stop signal: set before the call begins, the tool never runs; set while it runs, Task 10's worker kills it).
  - Task 7: `session.session.Emit = Callable[[str, dict], None]`; `session.session.RUNNABLE = ("proposed", "approved")` (the statuses `run` and `reject` accept); `Session.new(name="Untitled", **kw)` with `emit=`, `output_dir=`, `executor=`, `on_change=`; `Session.data` (`messages`, `steps`, `transcript`), `.artifacts`, `.executor`, `.changes`, `.on_change` (the autosave hook, a no-op when none was given; the session calls it after every change it makes, and the loop calls it after the changes it makes itself); `import_image(data, label) -> ArtifactMeta` (appends a change note naming the working copy, e.g. `the user added image a3f9c1d2 (lincoln_work)`, ruling R5, so the tests' `new_session` drains it with `take_changes()` and the tests that want it import their own pictures); `add_message(role, parts, step_ids=()) -> Message`; `propose(tool, raw, actor, reason=None) -> Step` (validates with `runner.validate(tool, raw, actor)`, resolves image refs, emits `step.proposed`); `run(step_id, raw=None, *, cancel: threading.Event | None = None) -> Step` (a `RUNNABLE` step only; edited `raw` validated and resolved as the user's before the step changes, so an EngineError leaves it `proposed`; emits `step.started` then `step.finished`/`step.failed`; `cancel` goes to the executor with the call, and a stopped call leaves the step `error` with the message `stopped by the user`); `reject(step_id, note=None) -> Step` (a `RUNNABLE` step; `result_text` becomes `rejected by user: <note>`); `run_tool(tool, raw, actor, reason=None) -> Step` (a `"user"` run appends to `changes`); `step(step_id) -> Step` (EngineError `no such step`); `summary() -> str`; `take_changes() -> list[str]`; `Step.result_text` as `run` stores it (one `key: a3f9c1d2 (label, WxH)` line per output then the tool's lines, or `error: <message>` and `hint: <hint>` for a failed step). The loop reads that field rather than calling the module's `result_text(step, artifacts)`, which cannot rebuild the tool's lines after the run.
  - Task 8 (tests only): `Session.edit(step_id, raw)`, `Session.replay_from(step_id)`, `Session.delete_last(step_id)`, each refusing a step that is `proposed` with EngineError `step N (<tool>) is waiting for approval`.
- Produces:
  - `agent/provider.py`: `@dataclass ToolCallRequest(id: str, name: str, arguments: dict | str)` (a str is JSON that didn't parse); `@dataclass Reply(text: str = "", tool_calls: list[ToolCallRequest] = [])`; `class ProviderError(Exception)`; `class Provider(Protocol)`: attribute `actor: str` (`"agent:<provider>"`) and `async complete(messages: list[dict], tools: list[dict], on_delta: Callable[[str], None]) -> Reply`. Messages and tools are OpenAI chat format.
  - `agent/fake.py`: `END_OF_SCRIPT = "(end of script)"`, `CHUNK = 12`; `class ScriptedProvider` with `actor = "agent:fake"`, `__init__(replies: list[Reply | ProviderError])`, `@classmethod from_file(path: Path | str) -> ScriptedProvider` (JSON list of `{"text": str, "tool_calls": [{"name": str, "arguments": dict | str}]}` or `{"error": str}`; ids `call_1`, `call_2`, ... across the whole script; any bad file is an EngineError with a hint), `async complete(...)` (streams `text` in `CHUNK`-character deltas, yielding to the loop before each; records a deep copy of each call's messages in `received: list[list[dict]]`; raises a scripted ProviderError; an exhausted script returns `Reply(text=END_OF_SCRIPT)`).
  - `agent/approval.py`: `MODES = ("auto", "ask_changes", "ask_all")`, `DECISIONS = ("approve", "reject", "edit")`; `needs_approval(spec: ToolSpec, mode: str) -> bool` (EngineError for an unknown mode); `@dataclass Decision(decision: Literal["approve","reject","edit"], params: dict | None = None, note: str | None = None)`; `class ApprovalGate`: `__init__(emit: Emit, resolve: Callable[[str], str] | None = None)` (`resolve` checks an edit's image refs: the server passes the current session's `artifacts.resolve`), `async request(step: Step) -> Decision` (emits `approval.needed {"step": <step json>}`), `respond(step_id: str, decision: str, params: dict | None = None, note: str | None = None) -> None` (EngineError, with the step still waiting, for a step that isn't waiting, an unknown decision, an edit without params, params with a decision other than edit, edited params that aren't valid as the user's, or, with `resolve`, an edited image ref the session doesn't have; emits `approval.resolved {"step_id", "decision", "note"}`), `pending() -> list[str]`, `cancel_all(note: str = "the user closed the app") -> None`. All four run on the event loop thread.
  - `agent/context.py`: `SYSTEM_PROMPT: str`, `UNANSWERED: str`; `tool_definitions() -> list[dict]` (`{"type": "function", "function": {"name", "description", "parameters": llm_schema(spec)}}` per registered tool); `image_placeholder(meta: ArtifactMeta) -> str` (`"[image a3f9c1d2: lincoln_work, 761x1000]"`); `build_messages(session: Session) -> list[dict]` (system prompt + `"Steps so far:\n" + session.summary()` or `"No steps yet."`, then a deep copy of `session.data.transcript` with an `UNANSWERED` tool result added for any tool call that has none).
  - `agent/loop.py`: `STOPPED = "stopped by the user"`, `FAILED = "the turn failed"`, `CHANGES_NOTE: str`; `Blocking = Callable[..., Awaitable[Any]]`; `@dataclass TurnConfig(approval_mode: str = "ask_changes", step_budget: int = 40, max_invalid: int = 3)`; `async run_turn(session: Session, provider: Provider, gate: ApprovalGate, text: str, attachments: list[str], cfg: TurnConfig, emit: Emit, blocking: Blocking = asyncio.to_thread) -> str` returning `"done" | "budget" | "invalid_calls" | "provider_error"`.
  - Events `run_turn` emits (the session adds `step.*`): `turn.started {}`; `message.done {"message": <Message json>}` for the system note, the user message and every assistant reply, and again for an assistant reply each time one of its calls becomes a step (right after that step's `step.proposed`; the message's `step_ids` now list it, so clients upsert messages by `id` and can hang every step card, an approval card included, on the reply that asked for it); `message.delta {"text"}`; `turn.finished {"reason"}` plus `"error": <message>` when the reason is `provider_error` or `error`.
  - Transcript entries it appends (OpenAI format): the changes note `{"role": "system", "content"}`, the user message `{"role": "user", "content": text + one placeholder line per attachment}`, each reply `{"role": "assistant", "content", "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": <JSON string>}}]}`, and one `{"role": "tool", "tool_call_id", "content"}` per call, whatever happened to it. Every transcript write, and every step id added to a message, is followed by `session.on_change()`, so an autosave never misses a tool result.

How the turn behaves (the tests below pin each point):
- `attachments` are artifact refs; they are resolved (through `blocking`) before anything is recorded or emitted, so a bad ref raises EngineError and the turn never starts.
- Whatever `session.take_changes()` returns opens the turn as one system note (`CHANGES_NOTE`, then `- <change>` per line), recorded before the user message: steps the user ran, Task 8's edits, replays and deletes, and images the user added without attaching them to a message (spec §5.3, ruling R5). The model hears each change once.
- A call is invalid when its arguments aren't a JSON object, the tool is unknown, or `session.propose` refuses it (bad parameters, a user-only field, an artifact ref that isn't in the session). Its tool result is `"error: <message>\nhint: <hint>"`, no step is made, and `max_invalid` of them in a row end the turn (`invalid_calls`). A valid call resets the count.
- A call that runs gets the step's `result_text` as its tool result, whether the step is `done` or `error` (a failed step is a result the model can react to, not an invalid call).
- `cfg.approval_mode` is read at every call, so the server switches modes mid-turn by assigning it. Reject gives the tool result `"rejected by user: <note or 'no reason given'>"`; edit runs `session.run(step_id, params)` and the result starts with `the user edited the parameters before it ran: <params json>`. An edit the gate let through (it had no `resolve`) that the session then refuses rejects the step, and the model hears `rejected by user: their edited parameters were refused (<message>)`.
- A step waiting for approval belongs to the gate: Task 8's `edit`, `replay_from` and `delete_last` refuse it (the tests pin this). If something settles it anyway before the decision is carried out (a direct `session.run` or `session.reject`, or a future method), the loop never raises over it: once the decision arrives it looks the step up without raising and answers the call with the step as it is, `result_text` for a step that ran or was rejected, `not run: the user deleted this step` for one that is gone, `not run: the user changed this step (it is <status> now)` otherwise. Such a step doesn't count against the budget. Stop answers the calls it has to answer the same way, except that a step that is gone by then gets `the user deleted this step` (it may have run first), and it only rejects steps that are still `proposed` or `approved`.
- The budget counts steps that ran (rejections and invalid calls don't). Once it is spent, every further call, in the same reply or a later one, is answered `not run: this turn's budget of N steps is used up; ...` and the turn ends with `budget`; a model that answers in text after spending exactly the budget ends with `done`.
- Stop is `task.cancel()`: every waiting approval is rejected (`gate.cancel_all(STOPPED)`), the executing step's own cancel event is set (see below), the session call under way is awaited (every session call goes through `blocking` shielded, so no thread is abandoned halfway), steps of the current reply still `proposed` or `approved` are rejected, every unanswered call gets a tool result (recorded, like every transcript write, with `session.on_change()`), `turn.finished {"reason": "stopped"}` is emitted and `CancelledError` propagates. Any other exception does the same with `FAILED` and `turn.finished {"reason": "error", "error": "<Type>: <message>"}`, then propagates.

Why Stop sets a per-step event and never calls `session.executor.cancel()`: the loop makes one `threading.Event` for each step it executes and passes it through `session.run(step_id, params, cancel=event)` to the executor with that step's call, and Stop sets it. `executor.cancel()` is the wrong tool here, for two reasons. It can only stop a call that has already entered the executor's `run()`: Task 10's `WorkerExecutor.run` clears its cancel flag when a call starts (so a cancel meant for an idle worker never trips a later call), so a Stop that lands after the step's thread was dispatched but before `run()` began (while `Session.run` validates the edit, names the outputs in `_stem`, computes `cache_key`, announces `step.started`, or waits for the server's lock) would be lost, and Stop would then wait for the whole tool, up to its time limit. And it is executor-wide: while this turn's step waits for the server's lock, the call holding the lock (the user's own `tools.run`, a replay, a CLI agent's step) is the one the shared executor is running, so `cancel()` would stop that call and let this one run in full. The event covers the whole way from dispatch to the end of the call and reaches only this step's call; an executor checks it before it starts the tool and while the tool runs, and the session's own `export` path checks it too. A stopped step ends `error` with `stopped by the user`, like any failed step, and its call's tool result says so. `test_a_stop_before_the_executor_begins_still_stops_the_step` holds the step's thread inside `Session.run` until Stop has landed and checks the tool never runs. `executor.cancel()` stays for callers with no event: `CoreApp.close()` (a replay's tool) and the server's shutdown (Task 13).

Notes for the server (Task 12) and the end-to-end test (Task 13):
- Run the turn with `blocking=` the app's locked call (`async with lock: return await asyncio.to_thread(fn, *args)`, as in `test_approvals_wait_outside_the_servers_lock`); approvals never take the lock, and `gate.respond` is called on the loop.
- Construct the gate as `ApprovalGate(self._emit, resolve=lambda ref: self.session.artifacts.resolve(ref))` (a lambda, because `session.new` and `session.open` replace `self.session`), so an edit naming an image the session doesn't have is an `approval.respond` error and the step keeps waiting for a good edit, instead of being rejected when it runs.
- `steps.edit`, `steps.delete` and `steps.replay_from` must refuse a step in `gate.pending()`. They already do through Task 8 (a waiting step is `proposed`, which `edit`, `replay_from` and `delete_last` refuse, pinned by `test_a_waiting_step_is_out_of_the_users_reach`), so the server adds no check of its own; if a later method can touch a waiting step, it must refuse it the same way. The loop's fallback for a step settled elsewhere (`test_a_step_settled_elsewhere_while_it_waited`) is a safety net, not a feature to rely on.
- The loop calls `session.on_change()` after its own writes (transcript entries, a step id added to a message), and those run through `blocking`, so the app's dirty flag plus "autosave after every `blocking` call" saves every tool result as it is recorded.
- Clients upsert messages by id: an assistant reply's `message.done` arrives once with `step_ids: []` and again after each `step.proposed` of its calls.
- Keep the `TurnConfig` of the running turn and assign `cfg.approval_mode` in `session.set_approval_mode`.
- `chat.stop` is `task.cancel()`; `on_client_gone()` is `gate.cancel_all()` then `task.cancel()` (tested here as the `client_gone` case of review focus 1's mechanism).
- The loop never calls `executor.cancel()` (pinned by `test_stop_while_waiting_for_approval`, `test_stop_while_a_tool_runs` and `test_a_stop_before_the_executor_begins_still_stops_the_step`): a turn's Stop reaches its running step through that step's own event, even while the step's call still waits for the app's lock. Task 12's `blocking` needs nothing for it, and a test executor the app runs turns on must take `run(call, cancel=None)` and honour the event.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_agent.py`:
```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_agent.py -q`
Expected: a collection error, `ModuleNotFoundError: No module named 'badshop.agent'`.

- [ ] **Step 3: Implement the provider protocol and the scripted provider**

`core/src/badshop/agent/__init__.py`:
```python
"""The in-app agent: a model art-directs through the session's tools, one turn at a time (spec §5.4)."""
```

`core/src/badshop/agent/provider.py`:
```python
"""What the agent loop needs from a model: one streamed completion in the OpenAI chat format.

Messages and tool definitions are OpenAI chat dicts (what LiteLLM takes, Plan 3). A provider streams its
text through `on_delta` as it arrives and returns the whole reply; a failed call raises ProviderError."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict | str  # a str when the model sent JSON that doesn't parse


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


class ProviderError(Exception):
    """The model call failed (auth, rate limit, context too long, network). The turn ends with its message."""


class Provider(Protocol):
    actor: str  # the actor its steps are recorded under: "agent:<provider>", e.g. "agent:fake"

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply: ...
```

`core/src/badshop/agent/fake.py`:
```python
"""A scripted stand-in for a model. The agent tests, the server's end-to-end test and the UI's
Playwright suite drive real turns with it: offline, fast and the same every time."""

import asyncio
import copy
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from badshop.agent.provider import ProviderError, Reply, ToolCallRequest
from badshop.engine.errors import EngineError
from badshop.tools.runner import explain

END_OF_SCRIPT = "(end of script)"
CHUNK = 12  # characters per streamed delta
SCRIPT_HINT = ('the file must be a JSON list like [{"text": "...", "tool_calls": [{"name": "find", '
               '"arguments": {"image": "a3f9c1d2"}}]}]')


class _ScriptCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict | str = Field(default_factory=dict)


class _ScriptReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = ""
    tool_calls: list[_ScriptCall] = []
    error: str | None = None  # the provider fails with this message instead of replying


class ScriptedProvider:
    """Plays `replies` in order, one per completion. A ProviderError in the list is raised at its turn."""

    actor = "agent:fake"

    def __init__(self, replies: list[Reply | ProviderError]):
        self.replies = list(replies)
        self.received: list[list[dict]] = []  # the messages of every completion, as they were sent
        self._next = 0

    @classmethod
    def from_file(cls, path: Path | str) -> "ScriptedProvider":
        """A JSON list of {"text", "tool_calls": [{"name", "arguments"}]} (or {"error": "..."}) entries.
        Tool call ids are generated in order across the whole script: call_1, call_2, ..."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # ValueError: bad JSON or not UTF-8
            raise EngineError(f"can't read the fake provider script {path} ({e})", hint=SCRIPT_HINT) from None
        try:
            entries = TypeAdapter(list[_ScriptReply]).validate_python(raw)
        except ValidationError as e:
            raise EngineError(f"the fake provider script {path} is not valid", hint=explain(e)) from None
        replies: list[Reply | ProviderError] = []
        n = 0
        for entry in entries:
            if entry.error is not None:
                replies.append(ProviderError(entry.error))
                continue
            calls = []
            for c in entry.tool_calls:
                n += 1
                calls.append(ToolCallRequest(id=f"call_{n}", name=c.name, arguments=c.arguments))
            replies.append(Reply(text=entry.text, tool_calls=calls))
        return cls(replies)

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply:
        self.received.append(copy.deepcopy(messages))
        if self._next < len(self.replies):
            reply = self.replies[self._next]
            self._next += 1
        else:
            reply = Reply(text=END_OF_SCRIPT)
        if isinstance(reply, ProviderError):
            raise reply
        for i in range(0, len(reply.text), CHUNK):
            await asyncio.sleep(0)  # a real stream waits on the network between chunks: Stop can land here
            on_delta(reply.text[i:i + CHUNK])
        return copy.deepcopy(reply)
```

- [ ] **Step 4: Implement the approval gate**

`core/src/badshop/agent/approval.py`:
```python
"""Approve-before-run (spec §7): which calls wait for the user, and the gate where they wait.

The gate lives on the event loop: `request` is awaited by the agent loop, `respond` and `cancel_all` are
called from the same loop (a client's `approval.respond`, Stop, or the last client going away)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from badshop.engine.errors import EngineError
from badshop.session.models import Step
from badshop.session.session import Emit
from badshop.tools.registry import ToolSpec, image_fields
from badshop.tools.runner import validate

MODES = ("auto", "ask_changes", "ask_all")
DECISIONS = ("approve", "reject", "edit")


def needs_approval(spec: ToolSpec, mode: str) -> bool:
    """auto: nothing waits. ask_changes: only read-only tools (find, info, view) run unasked; export, which
    writes a file but changes no image, waits like any other change. ask_all: everything waits."""
    if mode not in MODES:
        raise EngineError(f"unknown approval mode {mode!r}", hint=f"use one of: {', '.join(MODES)}")
    if mode == "auto":
        return False
    if mode == "ask_changes":
        return not spec.read_only
    return True


@dataclass
class Decision:
    decision: Literal["approve", "reject", "edit"]
    params: dict | None = None  # the user's parameters, for "edit"
    note: str | None = None  # why, for "reject"; the model hears it


class ApprovalGate:
    def __init__(self, emit: Emit, resolve: Callable[[str], str] | None = None):
        """`resolve` turns an image ref into a full artifact id or raises EngineError (the server passes the
        current session's `artifacts.resolve`, which never touches the disk and is safe to call while a
        tool runs). With it, an edit naming an image the session doesn't have is refused here and the step
        keeps waiting; without it, the session refuses that edit when the step runs."""
        self._emit, self._resolve = emit, resolve
        self._waiting: dict[str, tuple[Step, asyncio.Future]] = {}

    async def request(self, step: Step) -> Decision:
        """Announce the step and wait for the user's decision. If the waiting turn is cancelled, the entry
        stays until cancel_all() resolves and announces it."""
        fut = asyncio.get_running_loop().create_future()
        self._waiting[step.id] = (step, fut)
        self._emit("approval.needed", {"step": step.model_dump(mode="json")})
        return await fut

    def respond(self, step_id: str, decision: str, params: dict | None = None,
                note: str | None = None) -> None:
        """Resolve a waiting step. Edited parameters are validated here, as the user's, and their image refs
        checked when the gate has `resolve`: a bad edit raises EngineError and the step keeps waiting."""
        entry = self._waiting.get(step_id)
        if entry is None or entry[1].done():
            raise EngineError(f"step {step_id} is not waiting for approval",
                              hint="it was already decided, or its turn was stopped")
        step, fut = entry
        if decision not in DECISIONS:
            raise EngineError(f"unknown decision {decision!r}", hint=f"use one of: {', '.join(DECISIONS)}")
        if decision == "edit":
            if not isinstance(params, dict):
                raise EngineError("an edit needs the new parameters", hint="send params with the edit")
            checked = validate(step.tool, params, "user")
            if self._resolve is not None:
                dumped = checked.model_dump(mode="json")
                for name, is_list in image_fields(type(checked)).items():
                    value = dumped.get(name)
                    for ref in (value if is_list else [value]) if value is not None else []:
                        self._resolve(ref)  # EngineError "no such artifact: <ref>"
        elif params is not None:
            raise EngineError(f"parameters go with decision 'edit', not {decision!r}",
                              hint="send decision 'edit' to run the step with changed parameters")
        del self._waiting[step_id]
        fut.set_result(Decision(decision, params, note))
        self._emit("approval.resolved", {"step_id": step_id, "decision": decision, "note": note})

    def pending(self) -> list[str]:
        return [step_id for step_id, (_, fut) in self._waiting.items() if not fut.done()]

    def cancel_all(self, note: str = "the user closed the app") -> None:
        """Reject every waiting step (Stop, or no client left to answer)."""
        waiting, self._waiting = self._waiting, {}
        for step_id, (_, fut) in waiting.items():
            if not fut.done():
                fut.set_result(Decision("reject", note=note))
            self._emit("approval.resolved", {"step_id": step_id, "decision": "reject", "note": note})
```

- [ ] **Step 5: Implement the context builder**

`core/src/badshop/agent/context.py`:
```python
"""What the model sees: the system prompt, the tool definitions, and the conversation so far."""

import copy

from badshop.session.artifacts import short
from badshop.session.models import ArtifactMeta
from badshop.session.session import Session
from badshop.tools import REGISTRY
from badshop.tools.registry import llm_schema

# A placeholder until Plan 3 derives the real prompt from reference/SKILL.md. It carries the product rules
# (spec §3) and the one thing every model must know to call a tool at all: images are artifact ids.
SYSTEM_PROMPT = """\
You are the art director of badshop, an app for deliberately bad, 2005-forum-style photoshops. You make \
them by calling badshop's tools; the tools own every pixel.

Rules:
- Bad is the deliverable: hard-edged cut and paste, nearest-neighbor scaling, no blending, feathering, \
colour matching or shadows. Fix a placement at most once or twice, then stop.
- Never use or imitate an image-generation or inpainting model.
- Every image parameter takes an artifact id: the hex id of an image in this session, from a tool result \
or the user's message. The first 8 characters are enough (a3f9c1d2). File paths and URLs are not images; \
get new pictures with fetch, wiki, emoji or template.
- Images appear as placeholders like [image a3f9c1d2: lincoln_work, 761x1000]. Call view with the id to \
look at one, with grid=true to read coordinates. Use find for faces instead of guessing coordinates.
- The user can see, edit, reject and re-run every step. A rejected call comes back as "rejected by user: \
<note>": adapt to the note.
- When the picture is done, say in a sentence or two what you made."""

UNANSWERED = "not run: the app stopped before this call finished"


def tool_definitions() -> list[dict]:
    """Every tool in the OpenAI function format, with the schema a model may fill (no user-only fields)."""
    return [{"type": "function",
             "function": {"name": spec.name, "description": spec.description, "parameters": llm_schema(spec)}}
            for spec in REGISTRY.values()]


def image_placeholder(meta: ArtifactMeta) -> str:
    return f"[image {short(meta.id)}: {meta.label}, {meta.width}x{meta.height}]"


def _answered(transcript: list[dict]) -> list[dict]:
    """The transcript with a result for every tool call. Providers refuse a call left unanswered, which is
    what an autosave taken mid-call leaves behind if the core then dies."""
    out: list[dict] = []
    missing: list[str] = []
    for entry in transcript:
        if missing and entry.get("role") != "tool":
            out += [{"role": "tool", "tool_call_id": i, "content": UNANSWERED} for i in missing]
            missing = []
        out.append(entry)
        if entry.get("role") == "tool" and entry.get("tool_call_id") in missing:
            missing.remove(entry["tool_call_id"])
        if entry.get("role") == "assistant":
            missing = [c["id"] for c in entry.get("tool_calls") or []]
    out += [{"role": "tool", "tool_call_id": i, "content": UNANSWERED} for i in missing]
    return out


def build_messages(session: Session) -> list[dict]:
    """The system prompt plus the current step list, then the provider-format history (copied: a
    provider may rewrite what it is given)."""
    summary = session.summary()
    steps = f"Steps so far:\n{summary}" if summary else "No steps yet."
    system = f"{SYSTEM_PROMPT}\n\n{steps}"
    return [{"role": "system", "content": system}, *copy.deepcopy(_answered(session.data.transcript))]
```

- [ ] **Step 6: Implement the turn loop**

`core/src/badshop/agent/loop.py`:
```python
"""One agent turn (spec §5.4): ask the model, run its tool calls through the session with approvals,
feed the results back, and repeat until it answers without calls, the user stops it, the step budget
runs out, or it keeps making invalid calls."""

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from badshop.agent.approval import ApprovalGate, needs_approval
from badshop.agent.context import build_messages, image_placeholder, tool_definitions
from badshop.agent.provider import Provider, ProviderError, Reply, ToolCallRequest
from badshop.engine.errors import EngineError
from badshop.session.models import ArtifactMeta, Part, Step
from badshop.session.session import RUNNABLE, Emit, Session
from badshop.tools import registry

Blocking = Callable[..., Awaitable[Any]]  # asyncio.to_thread, or the server's locked version of it

STOPPED = "stopped by the user"
FAILED = "the turn failed"
CHANGES_NOTE = "Since your last turn the user changed the session (the step list is current):"


@dataclass
class TurnConfig:
    approval_mode: str = "ask_changes"  # read at every call: the server can switch it mid-turn
    step_budget: int = 40  # executed steps per turn
    max_invalid: int = 3  # consecutive invalid calls end the turn


def _arguments(call: ToolCallRequest) -> dict:
    args = call.arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            raise EngineError(f"the arguments for {call.name} are not valid JSON",
                              hint="send the arguments as one JSON object") from None
    if not isinstance(args, dict):
        raise EngineError(f"the arguments for {call.name} must be a JSON object",
                          hint="send the arguments as one JSON object")
    return args


def _error_text(e: EngineError) -> str:
    return f"error: {e.message}" + (f"\nhint: {e.hint}" if e.hint else "")


def _openai_call(call: ToolCallRequest) -> dict:
    args = call.arguments if isinstance(call.arguments, str) else json.dumps(call.arguments)
    return {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": args}}


# The functions below run through `blocking` (a worker thread), like every other session call.

def _attachments(session: Session, refs: list[str]) -> list[ArtifactMeta]:
    return [session.artifacts.meta[session.artifacts.resolve(r)] for r in refs]


def _record(session: Session, *entries: dict) -> None:
    """Append to the provider-format transcript. It is session state like any other, so the autosave
    hook hears of it: a restored session never has a call whose answer was only in memory."""
    session.data.transcript.extend(entries)
    session.on_change()


def _find(session: Session, step_id: str) -> Step | None:
    """The step, or None when the user deleted it (Session.step would raise)."""
    return next((s for s in session.data.steps if s.id == step_id), None)


def _as_it_is(step: Step) -> str:
    """The answer for a call whose step something other than this turn settled while it waited: how it
    ended (a run's result, a rejection and its note), or what it is now."""
    if step.status in ("done", "error", "rejected") and step.result_text:
        return step.result_text
    return f"not run: the user changed this step (it is {step.status} now)"


def _propose(session: Session, message_id: str, tool: str, raw: dict, actor: str,
             reason: str | None) -> tuple[Step, dict | None]:
    """Propose the call as a step of the reply's message. Returns the step and the message as JSON, now
    listing it (dumped here, under the caller's lock)."""
    step = session.propose(tool, raw, actor, reason)
    message = next((m for m in session.data.messages if m.id == message_id), None)
    if message is None:
        return step, None
    message.step_ids.append(step.id)
    session.on_change()
    return step, message.model_dump(mode="json")


def _reject(session: Session, step_id: str, note: str) -> str:
    """Carry out the user's rejection. Returns what the model hears back."""
    step = _find(session, step_id)
    if step is None:
        return "not run: the user deleted this step"
    if step.status not in RUNNABLE:  # settled elsewhere while it waited: answer with what happened
        return _as_it_is(step)
    session.reject(step_id, note)
    return f"rejected by user: {note}"


def _execute(session: Session, step_id: str, params: dict | None,
             cancel: threading.Event) -> tuple[bool, str]:
    """Run an approved (or user-edited) step, with `cancel` as its stop signal. Returns whether a tool ran,
    and what the model hears back."""
    step = _find(session, step_id)
    if step is None:
        return False, "not run: the user deleted this step"
    if step.status not in RUNNABLE:  # settled elsewhere while it waited: answer with what happened
        return False, _as_it_is(step)
    try:
        step = session.run(step_id, params, cancel=cancel)
    except EngineError as e:
        if params is None:  # a proposed step on its own params always runs: a bug, and the turn says so
            raise
        # The user's edit didn't resolve (an image id that isn't in the session, from a gate without
        # `resolve`). run() checks before it changes anything, so the step is still waiting: reject it.
        session.reject(step_id, f"the edited parameters were refused: {e.message}")
        return False, f"rejected by user: their edited parameters were refused ({e.message})"
    text = step.result_text  # the session's own report of the run: outputs, the tool's lines, or the error
    if params is not None:
        text = f"the user edited the parameters before it ran: {json.dumps(step.params)}\n{text}"
    return True, text


def _wind_up(session: Session, message_id: str | None, unanswered: dict[str, str | None], note: str) -> None:
    """After Stop (or a failure): reject the steps this turn left waiting, and answer every call left
    without a result, so the transcript stays one a provider accepts. Only steps still `proposed` or
    `approved` are rejected; a step something else settled is answered as it is, a deleted one as deleted,
    and nothing here raises over a step that changed or is gone."""
    message = next((m for m in session.data.messages if m.id == message_id), None)
    ours = [*(message.step_ids if message else []), *(s for s in unanswered.values() if s)]
    stopped = set()
    for step_id in dict.fromkeys(ours):
        step = _find(session, step_id)
        if step is not None and step.status in RUNNABLE:
            session.reject(step_id, note)
            stopped.add(step_id)
    entries = []
    for call_id, step_id in unanswered.items():
        step = _find(session, step_id) if step_id else None
        if step_id is None or step_id in stopped:
            content = f"not run: {note}"
        elif step is None:  # it finished, then the user deleted it, before this turn could answer
            content = "the user deleted this step"
        else:
            content = _as_it_is(step)  # a result that came in as Stop landed, or a step settled elsewhere
        entries.append({"role": "tool", "tool_call_id": call_id, "content": content})
    if entries:
        _record(session, *entries)


class _Turn:
    def __init__(self, session: Session, provider: Provider, gate: ApprovalGate, cfg: TurnConfig,
                 emit: Emit, blocking: Blocking):
        self.session, self.provider, self.gate, self.cfg = session, provider, gate, cfg
        self.emit, self.blocking = emit, blocking
        self.executed = 0  # steps run this turn (the budget)
        self.invalid = 0  # consecutive invalid calls
        self.message_id: str | None = None  # the assistant message of the reply being handled
        self.unanswered: dict[str, str | None] = {}  # its call ids without a result -> their step ids
        self.inflight: asyncio.Task | None = None  # the session call under way
        self.stopping: threading.Event | None = None  # the executing step's own stop signal: Stop sets it
        self.error: str | None = None  # the provider's error message

    async def call(self, fn: Callable, *args: Any) -> Any:
        """`fn(*args)` through `blocking`, shielded from cancellation: Stop waits for it to end rather
        than abandon a thread halfway through changing the session."""
        self.inflight = asyncio.ensure_future(self.blocking(fn, *args))
        result = await asyncio.shield(self.inflight)
        self.inflight = None
        return result

    async def message(self, role: str, parts: list[Part]) -> str:
        m = await self.call(self.session.add_message, role, parts)
        self.emit("message.done", {"message": m.model_dump(mode="json")})
        return m.id

    async def answer(self, call_id: str, content: str) -> None:
        self.unanswered.pop(call_id, None)  # before recording: Stop must never answer a call twice
        await self.call(_record, self.session, {"role": "tool", "tool_call_id": call_id, "content": content})

    async def answer_rest(self, content: str) -> None:
        for call_id in list(self.unanswered):
            await self.answer(call_id, content)

    def delta(self, chunk: str) -> None:
        self.emit("message.delta", {"text": chunk})

    async def run(self, text: str, images: list[ArtifactMeta]) -> str:
        changes = await self.call(self.session.take_changes)
        if changes:
            note = "\n".join([CHANGES_NOTE, *(f"- {c}" for c in changes)])
            await self.call(_record, self.session, {"role": "system", "content": note})
            await self.message("system_note", [Part(type="text", text=note)])
        lines = ([text] if text else []) + [image_placeholder(m) for m in images]
        await self.call(_record, self.session, {"role": "user", "content": "\n".join(lines)})
        await self.message("user", ([Part(type="text", text=text)] if text else [])
                           + [Part(type="image", artifact_id=m.id) for m in images])
        tools = tool_definitions()
        while True:
            messages = await self.call(build_messages, self.session)
            try:
                reply = await self.provider.complete(messages, tools, self.delta)
            except ProviderError as e:
                self.error = str(e)
                return "provider_error"
            reason = await self.handle(reply)
            if reason:
                return reason

    async def handle(self, reply: Reply) -> str | None:
        entry: dict = {"role": "assistant", "content": reply.text}
        if reply.tool_calls:  # OpenAI's shape: content may be null when the reply only calls tools
            entry.update(content=reply.text or None, tool_calls=[_openai_call(c) for c in reply.tool_calls])
        self.unanswered = {c.id: None for c in reply.tool_calls}
        await self.call(_record, self.session, entry)
        self.message_id = await self.message("assistant",
                                             [Part(type="text", text=reply.text)] if reply.text else [])
        if not reply.tool_calls:
            return "done"
        why = reply.text.strip()[:500] or None  # the model's stated reason, shown on approval cards
        for call in reply.tool_calls:
            if self.executed >= self.cfg.step_budget:
                await self.answer_rest(f"not run: this turn's budget of {self.cfg.step_budget} steps is used "
                                       "up; the user can send a message to continue")
                return "budget"
            await self.handle_call(call, why)
            if self.invalid >= self.cfg.max_invalid:
                await self.answer_rest(f"not run: {self.cfg.max_invalid} invalid calls in a row ended the "
                                       "turn")
                return "invalid_calls"
        return None

    async def handle_call(self, call: ToolCallRequest, why: str | None) -> None:
        try:
            spec = registry.get(call.name)
            args = _arguments(call)
            step, message = await self.call(_propose, self.session, self.message_id, call.name, args,
                                            self.provider.actor, why)
        except EngineError as e:  # bad JSON, unknown tool, bad or user-only parameters, unknown artifact
            self.invalid += 1
            await self.answer(call.id, _error_text(e))
            return
        self.invalid = 0
        self.unanswered[call.id] = step.id
        if message is not None:  # the reply again, now listing the step: clients upsert messages by id
            self.emit("message.done", {"message": message})
        params = None
        if needs_approval(spec, self.cfg.approval_mode):
            decision = await self.gate.request(step)
            if decision.decision == "reject":
                content = await self.call(_reject, self.session, step.id, decision.note or "no reason given")
                await self.answer(call.id, content)
                return
            params = decision.params if decision.decision == "edit" else None
        self.stopping = threading.Event()  # one per step: it goes with this call and no other
        ran, content = await self.call(_execute, self.session, step.id, params, self.stopping)
        self.stopping = None
        if ran:
            self.executed += 1
        await self.answer(call.id, content)

    async def stop(self, note: str) -> None:
        """Stop mid-turn: reject waiting approvals, stop the step being executed, let the session call under
        way finish, then leave the session and its transcript consistent."""
        self.gate.cancel_all(note)
        if self.stopping is not None:  # this step's call only, whether or not it has reached the executor
            self.stopping.set()
        if self.inflight is not None:
            await asyncio.wait([self.inflight])  # a stopped tool ends at once; its step records how it ended
        await self.blocking(_wind_up, self.session, self.message_id, dict(self.unanswered), note)


async def run_turn(session: Session, provider: Provider, gate: ApprovalGate, text: str,
                   attachments: list[str], cfg: TurnConfig, emit: Emit,
                   blocking: Blocking = asyncio.to_thread) -> str:
    """Run one turn and return why it ended: "done", "budget", "invalid_calls" or "provider_error".

    Stop is cancelling the task that runs this: pending approvals are rejected, a running tool is killed,
    `turn.finished {"reason": "stopped"}` is emitted and CancelledError propagates. Any other exception
    ends the turn with `turn.finished {"reason": "error"}` and propagates. An attachment that doesn't
    resolve raises EngineError before anything is recorded or emitted."""
    images = await blocking(_attachments, session, attachments)
    turn = _Turn(session, provider, gate, cfg, emit, blocking)
    emit("turn.started", {})
    try:
        reason = await turn.run(text, images)
    except asyncio.CancelledError:
        try:
            await turn.stop(STOPPED)
        finally:
            emit("turn.finished", {"reason": "stopped"})
        raise
    except Exception as e:
        try:
            await turn.stop(FAILED)
        finally:
            emit("turn.finished", {"reason": "error", "error": f"{type(e).__name__}: {e}"})
        raise
    emit("turn.finished", {"reason": reason, **({"error": turn.error} if turn.error else {})})
    return reason
```

- [ ] **Step 7: Run the tests**

Run: `cd core && uv run pytest tests/test_agent.py -q`
Expected: `45 passed` in about 4 seconds, offline (31 test functions; the parametrized ones count once per case: 12 for `test_a_step_settled_elsewhere_while_it_waited`, 3 for `test_scripted_provider_bad_file`, 2 for `test_stop_while_waiting_for_approval`). Every wait has a 10 s limit, so a lost decision or a missing event shows up as a `TimeoutError` failure, never a hung suite.

Then the whole suite and the linter: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1273 passed, 1 deselected` in about a minute and a half (Task 10's 1228 plus these 45; the deselected one is the `network` test), and ruff prints `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add core/src/badshop/agent core/tests/test_agent.py
git commit -m "feat(agent): provider protocol, scripted fake provider, approval gate and turn loop

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Server core: settings, JSON-RPC dispatcher, CoreApp methods and events (no sockets)

**Files:**
- Create: `core/src/badshop/server/__init__.py`, `core/src/badshop/server/settings.py`, `core/src/badshop/server/rpc.py`, `core/src/badshop/server/app.py`
- Modify: `core/pyproject.toml` and `core/uv.lock` (the runtime dependencies `websockets>=15,<17` and `psutil>=6`, through `uv add`; the `badshop-core` script comes with Task 13's `server/main.py`)
- Test: `core/tests/test_server_app.py`

**Interfaces:**
- Consumes:
  - Plan 1: `engine.errors.EngineError(message, hint=None)`; `engine.common.fit(im, longest) -> tuple[Image, float]`, `has_alpha(im) -> bool`, `to_rgb(im) -> Image`; `badshop.tools.REGISTRY: dict[str, ToolSpec]`.
  - Task 2: `registry.get(name) -> ToolSpec`, `registry.llm_schema(spec) -> dict`, `registry.ui_schema(spec) -> dict`, `ToolSpec.writes_files`; `runner.validate(name, raw, actor="user") -> Params`, `runner.is_trusted(actor) -> bool`, `runner.explain(e: ValidationError) -> str`.
  - Task 4: `assets.PROGRESS: Callable[[str, int, int | None], None] | None`; `manifest.status() -> list[dict]` (`name, label, approx_mb, present`); `manifest.download(name) -> Path`.
  - Task 5: `files.default_output_dir() -> Path`; `ArtifactStore.meta: dict[str, ArtifactMeta]`, `.resolve(ref) -> str` (EngineError `no such artifact: <ref>`; never touches the disk and snapshots its keys, so it is safe to call on the event loop while a session call runs in a thread), `.data(id) -> bytes`, `.image(id) -> Image`; `ArtifactMeta.mime`, `.original_id`, `.width`, `.label`, `.format`. The store turns a file name into a label (its stem, slugified; `"pasted"` when empty), so CoreApp passes names through unchanged. `import_image` labels the working copy `<stem>_work` and the original `<stem>` (`trump.png` gives `trump_work`, and exporting it without a name writes `trump_work.png`); a small upright PNG that already is its own working copy, like both test fixtures, is stored once (working and original are the same artifact, `original_id` None), so `artifacts.import` returns that one meta as both.
  - Task 6: `execution.Executor` (Protocol: `run(call, cancel: threading.Event | None = None) -> ToolOutcome`, `cancel()`, `close()`; the event is one call's own stop signal, which Task 7's `Session._execute` always passes, so a test executor takes `cancel=None` too); tests use `InProcessExecutor()` and `ToolOutcome(ok, ..., error_message=...)`.
  - Tasks 7-8: `session.session.RUNNABLE = ("proposed", "approved")`; `Session.new(name, *, executor, emit, output_dir, on_change)`; attributes `data`, `artifacts`, `executor`, `output_dir`; `import_image(data, label, source=None) -> ArtifactMeta` (the working copy); `propose(tool, raw, actor, reason=None) -> Step`; `run(step_id, raw=None, *, cancel=None) -> Step` (a `RUNNABLE` step only, else EngineError; an edited `raw` is validated and resolved as the user's before the step changes, so an EngineError there leaves it `proposed`; a tool's own failure is a failed step, never an exception; `cancel` is Task 11's per-step stop signal, and CoreApp passes none); `reject(step_id, note=None) -> Step` (a `RUNNABLE` step; `result_text` becomes `rejected by user: <note>`); `run_tool(tool, raw, actor, reason=None) -> Step`; `export(artifact_id, name) -> Path`; `step(step_id) -> Step` (EngineError `no such step`); `edit(step_id, raw) -> list[Step]`; `replay_from(step_id, *, use_cache=True) -> list[Step]`; `delete_last(step_id) -> None` (emits `step.deleted {"step_id": <the deleted step's id>}` once the step is gone; ruling R7 adds this event to spec 7's list, and the carry-forward doc records it). `edit`, `replay_from` and `delete_last` refuse a step that is `proposed`, `approved` or `running`, so a step waiting in a gate is out of the user's reach. `SessionData.approval_mode`, `.steps`, `.transcript`; `Step.id`, `.status`, `.actor`, `.tool`, `.params`, `.outputs`, `.error`, `.result_text`.
  - Task 9: `project.save(session, path) -> Path`, `open_project(path, **session_kw) -> Session`, `export_recipe(session) -> dict`, `autosave(session) -> None`, `autosave_path() -> Path`, `find_autosave() -> Path | None`, `claim_autosave() -> Path | None` (moves an existing `autosave/session.badshop` to `autosave/previous.badshop` with `os.replace` and returns that path; with nothing to move, a `previous.badshop` that no later run replaced is still returned; `None` when there is neither. It creates nothing and never raises: a file it can't move stays where it is, for the next launch, and it returns `None`).
  - Task 10: `WorkerExecutor(timeout_s=..., max_rss_mb=...)`, the default `executor_factory`. CoreApp itself calls `cancel()` only in `CoreApp.close()`, right before the executor's `close()`; stopping a turn's running tool is run_turn's job, through that step's own cancel event (Task 11), never `cancel()`.
  - Task 11: `ScriptedProvider.from_file(path)`, which turns every bad file into its own EngineError: `can't read the fake provider script <path> (<reason>)` for a missing, unreadable or non-JSON file, `the fake provider script <path> is not valid` for a wrong shape (CoreApp passes it through unchanged); `ApprovalGate(emit, resolve=None)`, `await gate.request(step) -> Decision` (`.decision`, `.params`, `.note`), `gate.respond(step_id, decision, params=None, note=None)` (EngineError, with the step still waiting, when the step isn't waiting, for an edit whose params aren't valid as the user's, and, with `resolve`, for an edited image ref the session doesn't have), `gate.pending() -> list[str]`, `gate.cancel_all(note)` (every waiting request resolves as reject with that note); `approval.needs_approval(spec, mode) -> bool`; `TurnConfig(approval_mode, step_budget, max_invalid)`; `await run_turn(session, provider, gate, text, attachments, cfg, emit, blocking=...) -> str`. run_turn routes every session call through `blocking`, emits `turn.started`, and emits `turn.finished` itself once it has started: on Stop it calls `gate.cancel_all`, rejects the steps it left waiting, answers every open call, emits `{"reason": "stopped"}` and re-raises `CancelledError`; any other exception gives `{"reason": "error", "error"}` and is re-raised. Its transcript writes call `session.on_change()`, so they autosave like any other change. Task 11 asks the server to build its gate with `resolve` against the open session, which CoreApp does for both of its gates.
- Produces:
  - `server/settings.py`: `ApprovalMode = Literal["auto", "ask_changes", "ask_all"]`; `FILE = "settings.json"`; `class Settings(BaseModel)` (`extra="forbid"`, `allow_inf_nan=False`): `approval_mode: ApprovalMode = "ask_changes"`, `auto_replay: bool = True`, `output_dir: str | None = None` (must be absolute), `step_budget: int = 40` (1-500), `tool_timeout_s: float = 120.0` (1-3600), `tool_memory_mb: int = 3072` (256-65536), `fake_provider_script: str | None = None`; `config_dir() -> Path` (`$BADSHOP_CONFIG_DIR` or `platformdirs.user_config_dir("badshop", appauthor=False)`); `settings_path() -> Path`; `load_settings() -> Settings` (a missing or corrupt file gives the defaults; invalid values and unknown keys are dropped); `save_settings(s: Settings) -> None` (atomic; an OSError becomes `EngineError`).
  - `server/rpc.py`: `PARSE_ERROR=-32700`, `INVALID_REQUEST=-32600`, `METHOD_NOT_FOUND=-32601`, `INVALID_PARAMS=-32602`, `INTERNAL_ERROR=-32603`, `ENGINE_ERROR=-32000` (data `{"hint": ...}`), `FORBIDDEN=-32001`; `ACTORS = ("user", "any")`; `class RpcError(Exception)` with `(code: int, message: str, data: dict | None = None)`; `notification(method: str, params: dict) -> str` (a module function); `params_model(name: str, fn) -> type[BaseModel]`; `class Dispatcher` with `method(name: str, *, actors: str = "user")` (a decorator; `ValueError` for a duplicate name or an unknown `actors`), `names() -> list[str]`, and `async handle(raw: str, actor: str) -> str | None` (a frame `json.loads` refuses is PARSE_ERROR with `"id": null`: a `ValueError` for text that isn't JSON, and a `RecursionError` for JSON nested deeper than the parser goes, such as `"[" * 100_000`). Handler convention: `async def handler(actor: str, **params) -> JSON-safe result`. The keyword parameters, with their annotations and defaults, are the method's schema.
  - `server/app.py`: `MAX_IMPORT_BYTES = 200 * 2**20`; `class CoreApp` with `__init__(self, settings: Settings | None = None, executor_factory: Callable[..., Executor] = WorkerExecutor)`. Construct it inside the running event loop; before anything can autosave, `__init__` calls `project.claim_autosave()` (which never raises; CoreApp still guards the call, so an unexpected `EngineError` or `OSError` there would be logged and only cost the restore offer). The factory is called as `executor_factory(timeout_s=settings.tool_timeout_s, max_rss_mb=settings.tool_memory_mb)`. Attributes: `settings`, `session`, `path`, `gate` (the in-app turn's approval gate; CLI agents' calls wait in a second, private one, so Stop never touches them), `dispatcher`. Methods: `subscribe(send: Callable[[str], Awaitable[None]]) -> Callable[[], None]`, `on_client_gone() -> None`, `async close() -> None`.
  - For the transport (Task 13): every handler may be cancelled, and a closed connection's in-flight `dispatcher.handle` tasks should be. A session call already inside its thread finishes first and holds the lock until then (the lock is never released under a running thread); a cancelled non-user `tools.run` rejects its step unless it already ran; a `session.new`, `session.open` or `session.restore` cancelled once its swap is inside its thread still completes the swap and rejects the old session's waiting CLI calls, while one cancelled as it waits for the lock changes nothing (the open session and its waiting calls stay as they are).
  - RPC methods (params → result). "Snapshot" means `SessionData.model_dump(mode="json", by_alias=True)` (top-level `schema`, `id`, `name`, `approval_mode`, `messages`, `steps`, `artifacts`, `transcript`...) plus four app keys: `"path": str | None` (the project file), `"turn_running": bool`, `"pending_approvals": [step ids]` (the turn's, then the CLI agents'), and `"restorable": str | None` (the last run's autosave that `claim_autosave` moved aside at startup, until `session.restore` takes it; spec 9 and 10).

    | method | actors | params → result |
    |---|---|---|
    | `session.new` | user | `{name?}` → snapshot (refused while a turn runs; the old session's waiting CLI calls are rejected) |
    | `session.get` | user | `{}` → snapshot |
    | `session.open` | user | `{path}` → snapshot (as `session.new`; any failure leaves the session untouched; a file in the autosave folder opens with `path: null`) |
    | `session.restore` | user | `{}` → snapshot (opens the file `restorable` names with `path: null`, as `session.new` does; ENGINE_ERROR `there is no autosaved session to restore` when there is none; a restore clears `restorable`, a failed one changes nothing) |
    | `session.save` | user | `{}` → `{"path"}` |
    | `session.save_as` | user | `{path}` → `{"path"}` |
    | `session.export_recipe` | user | `{path}` → `{"path"}` |
    | `session.set_approval_mode` | user | `{mode}` → snapshot (also mid-turn: the running turn follows the new mode from its next tool call, and a call already waiting keeps waiting; a CLI agent's call follows `session.data.approval_mode` as it is when the call is made; the settings' `approval_mode`, the mode new sessions start in, is not changed) |
    | `chat.send` | user | `{text, attachments?}` → `{"started": true}` (refused while a turn runs, and while a `session.new`, `session.open` or `session.restore` is under way) |
    | `chat.stop` | user | `{}` → `{"stopped": bool}` (returns once the turn has ended; CLI agents' calls keep waiting) |
    | `tools.list` | any | `{}` → `[{name, summary, description, category, mutates, network, read_only, writes_files, schema}]` |
    | `tools.run` | any | `{tool, params?}` → step (a non-user actor's call waits for approval as the session's mode requires; a rejection, or an edit the session refuses, returns it `rejected`) |
    | `steps.edit` | user | `{step_id, params}` → `{"stale": [ids]}` (and a background `replay_from` when `auto_replay`) |
    | `steps.replay_from` | user | `{step_id}` → `[steps]` (the steps it ran) |
    | `steps.delete` | user | `{step_id}` → `{"deleted": step_id}` (every subscriber also gets the session's `step.deleted {"step_id"}` event) |
    | `approval.respond` | user | `{step_id, decision, params?, note?}` → `{"ok": true}` (either gate; a bad edit, including an image id the session doesn't have, is an ENGINE_ERROR and the step keeps waiting) |
    | `artifacts.get` | any | `{id, max_px?}` (16-4096) → `{"meta", "mime", "data"}` (base64) |
    | `artifacts.import` | user | `{path? \| data?, name?}` → `{"working", "original"}` |
    | `export` | user | `{artifact_id, name?}` → `{"path"}` |
    | `settings.get` / `settings.set` | user | `{}` / `{values}` → the settings |
    | `assets.status` | user | `{}` → `manifest.status()` |
    | `assets.download` | user | `{name}` → `{"path"}` |

  - Events CoreApp emits itself: `asset.progress {name, done, total}`, `core.log {level, message}`, and `turn.finished`, but only when run_turn didn't announce the end: `{"reason": "stopped"}` for a turn cancelled before that, or `{"reason": "error", "error": "<Type>: <message>"}` when run_turn raised. All other events come from `Session`, `ApprovalGate` and `run_turn` through the app's `emit`, which forwards each one unchanged to every subscriber: from `Session`, `step.proposed`, `step.started`, `step.finished`, `step.failed` (each `{"step", "artifacts"}`), `step.stale {"step_ids"}` and `step.deleted {"step_id"}` (Task 8's `delete_last`, ruling R7; not in spec 7's list, so the carry-forward doc records it); from the gates, `approval.needed {"step"}` and `approval.resolved {"step_id", "decision", "note"}`; from `run_turn`, `turn.started {}`, `message.delta {"text"}`, `message.done {"message"}` and `turn.finished {"reason"}`. Plan 2 sends no `step.progress` and no `provider.status`.

How the pieces fit (read before implementing):
- **One lock, threads for blocking work.** Every call that changes the session goes through `CoreApp._blocking(fn, *args)`. It holds one `asyncio.Lock`, runs `fn` in `asyncio.to_thread`, and afterwards autosaves in the same thread when the session changed (`Session.on_change` sets a dirty flag). `run_turn` gets `_blocking` as its `blocking` parameter, so agent steps and user steps never interleave. Approvals wait outside the lock. A thread can't be interrupted, so a cancelled caller holds the lock until its thread ends; the lock is never released while a thread is inside the session. A turn's Stop stops its running step through that step's own cancel event, which `Session.run` hands to the executor with the call (Task 11), so it works even while the step's call still waits for this lock, and it never touches a call another caller is running; `close()` calls the executor's `cancel()` before closing the executor, for a tool a replay is running. Reading an artifact (`artifacts.get`) and the asset calls take no lock: artifacts are immutable, and a 170 MB download must not hold up tools.
- **Events.** `_emit` works from any thread. From a worker thread it hops to the loop with `call_soon_threadsafe`, and each subscriber gets its own queue and a pump task, so events arrive in order and a slow client never blocks a session call. `_emit` passes on any event name it is given, so an event a session method adds (Task 8's `step.deleted`) reaches every client with no change here; `test_edit_replays_the_later_steps` pins that one.
- **Autosave and the restore offer.** Nothing autosaves until the session changes, so a core that starts and quits untouched leaves no autosave. A turn ends with one more autosave of the session as it left it (`_blocking(self._changed)`), on top of the ones after each of its session calls. Spec 9 and 10 (after a crash the next launch, or the shell's restart of the core, offers to restore the autosave) need the last run's autosave to survive this run's first change, which autosaves to the same file. So `__init__` calls `project.claim_autosave()` before anything can autosave: it moves `autosave/session.badshop` to `autosave/previous.badshop` and returns that path, which the snapshot reports as `restorable`. `session.restore` opens it through `_switch` with `path: null` (the autosave is not the user's project file, and Save must not write into it), clears `restorable`, and marks the session changed, so this run's autosave holds the restored session at once. A claim that can't move the file returns `None` (the file stays for the next launch) and the core starts without an offer. `session.open` gives `path: null` to any file in the autosave folder too.
- **Switching sessions.** `session.new`, `session.open` and `session.restore` go through `_switch`: after the idle check it counts itself in `_switching` until the swap is done, and `chat.send` refuses while that count is non-zero. Both checks run on the loop with no await between check and reservation, so a turn never starts on a session that is being replaced (the swap waits for the lock, so a user tool can hold it for a while); the swap function checks for a turn again under the lock. Handlers that act on "the" session read `self.session` inside their locked call (`tools.run`, `steps.edit`, `session.save`), so a swap between a request's arrival and its turn at the lock can't send it to the old session.
- **Actors and the two gates.** Only `"user"` may call the `user` methods (`FORBIDDEN` otherwise). A non-user `tools.run` is proposed as that actor, so `Session.propose` enforces artifact-id-only refs and user-only fields, and then waits for approval as the session's mode asks, like the in-app agent's calls (spec 7, "the same gate applies to CLI agents"). It waits in its own gate (`_cli_gate`): Stop (spec 5.4) is about the in-app turn, whose `run_turn` cancels `self.gate`, so a CLI agent is never told the user rejected a call the user never saw rejected. A closed UI (`on_client_gone`), a new, opened or restored session and `close()` cancel both gates. `approval.respond` answers whichever gate holds the step, and both gates check an edit's image ids against the open session (Task 11's `resolve`). A CLI step never stays `proposed`: a rejection rejects it (`_settle`), an approved or edited step runs in one locked call that rejects it if `Session.run` still refuses the edit (`_run_or_reject`, the same fallback as Task 11's `_execute`), and a caller that is cancelled at any point after the step was proposed rejects it before letting go.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_server_app.py`:
```python
"""Server core (Task 12): settings, the JSON-RPC dispatcher, and CoreApp's methods and events.

No sockets: a `Client` here does what one WebSocket connection does in server/ws.py (Task 13), it
subscribes to events and sends JSON-RPC frames through `app.dispatcher.handle`. Tools run through
InProcessExecutor (the worker has its own tests), and only tools that need no download are used."""

import asyncio
import base64
import io
import json
import threading
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine import assets, manifest
from badshop.engine.errors import EngineError
from badshop.server import app as server_app
from badshop.server import rpc
from badshop.server.app import CoreApp
from badshop.server.rpc import Dispatcher, RpcError
from badshop.server.settings import Settings, config_dir, load_settings, save_settings, settings_path
from badshop.session import project
from badshop.session.execution import InProcessExecutor, ToolOutcome
from badshop.session.session import Session
from conftest import FIXTURES

LINCOLN = (FIXTURES / "lincoln.png").read_bytes()
TRUMP = FIXTURES / "trump.png"
HEAD = [100, 50, 350, 330]  # a box on lincoln's 457x600 working copy
METHODS = sorted([
    "session.new", "session.get", "session.open", "session.restore", "session.save", "session.save_as",
    "session.export_recipe", "session.set_approval_mode", "chat.send", "chat.stop", "tools.list",
    "tools.run", "steps.edit", "steps.replay_from", "steps.delete", "approval.respond", "artifacts.get",
    "artifacts.import", "export", "settings.get", "settings.set", "assets.status", "assets.download",
])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Private config, data (autosave) and output folders for one test."""
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BADSHOP_OUT", str(tmp_path / "out"))
    monkeypatch.delenv("BADSHOP_FAKE_PROVIDER", raising=False)
    return tmp_path


# --- settings -----------------------------------------------------------------------------------


def test_settings_round_trip_and_bad_files(env):
    assert config_dir() == env / "config"
    assert load_settings() == Settings()  # no file yet
    s = Settings(approval_mode="auto", step_budget=7, output_dir=str(env / "pics"))
    save_settings(s)
    assert load_settings() == s
    assert [p.name for p in config_dir().iterdir()] == ["settings.json"]  # the temp file was renamed away
    settings_path().write_text("{not json", encoding="utf-8")
    assert load_settings() == Settings()
    settings_path().write_text("[1, 2]", encoding="utf-8")
    assert load_settings() == Settings()
    # a value that is no longer valid, and a key from a newer version, are dropped; the rest is kept
    settings_path().write_text(json.dumps({"step_budget": 0, "auto_replay": False, "from_the_future": 1}),
                               encoding="utf-8")
    assert load_settings() == Settings(auto_replay=False)


def test_settings_bounds():
    assert Settings().model_dump() == {
        "approval_mode": "ask_changes", "auto_replay": True, "output_dir": None, "step_budget": 40,
        "tool_timeout_s": 120.0, "tool_memory_mb": 3072, "fake_provider_script": None}
    for bad in ({"step_budget": 0}, {"step_budget": 501}, {"tool_timeout_s": 0.5}, {"tool_timeout_s": 3601},
                {"tool_timeout_s": float("inf")}, {"tool_memory_mb": 255}, {"tool_memory_mb": 65537},
                {"approval_mode": "yolo"}, {"output_dir": "relative/folder"}, {"nope": 1}):
        with pytest.raises(ValidationError):
            Settings(**bad)


# --- the dispatcher -----------------------------------------------------------------------------


def _dispatcher() -> Dispatcher:
    d = Dispatcher()

    @d.method("echo", actors="any")
    async def echo(actor: str, text: str, times: int = 1) -> dict:
        return {"actor": actor, "text": text * times}

    @d.method("secret")
    async def secret(actor: str) -> str:
        return "for the user only"

    @d.method("engine")
    async def engine(actor: str) -> None:
        raise EngineError("no such artifact: abc123", hint="use an artifact id")

    @d.method("custom")
    async def custom(actor: str) -> None:
        raise RpcError(rpc.INVALID_PARAMS, "give either path or data")

    @d.method("bug")
    async def bug(actor: str) -> None:
        raise ZeroDivisionError("oops")

    @d.method("unencodable")
    async def unencodable(actor: str) -> object:
        return object()

    return d


def _ask(d: Dispatcher, msg, actor: str = "user") -> dict | None:
    reply = asyncio.run(d.handle(msg if isinstance(msg, str) else json.dumps(msg), actor))
    return None if reply is None else json.loads(reply)


def _req(method: str, params=None, id=1) -> dict:
    msg = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def test_dispatcher_results():
    d = _dispatcher()
    assert _ask(d, _req("echo", {"text": "ab", "times": 2}, id="x")) == {
        "jsonrpc": "2.0", "id": "x", "result": {"actor": "user", "text": "abab"}}
    assert _ask(d, _req("echo", {"text": "hi"}), "cli:claude")["result"] == {"actor": "cli:claude",
                                                                           "text": "hi"}
    assert _ask(d, _req("secret"))["result"] == "for the user only"  # params may be left out
    # a notification (no id) runs but gets no reply, even when it fails
    assert _ask(d, {"jsonrpc": "2.0", "method": "echo", "params": {"text": "x"}}) is None
    assert _ask(d, {"jsonrpc": "2.0", "method": "engine"}) is None
    with pytest.raises(ValueError):
        d.method("echo")  # registering a name twice
    with pytest.raises(ValueError):
        d.method("other", actors="agents")


def test_dispatcher_errors():
    d = _dispatcher()

    def error(msg, actor="user") -> dict:
        reply = _ask(d, msg, actor)
        assert set(reply) == {"jsonrpc", "id", "error"}
        return reply["error"] | {"id": reply["id"]}

    assert error("{nope")["code"] == rpc.PARSE_ERROR
    assert error("{nope")["id"] is None
    # nesting deeper than json's scanner goes raises RecursionError, not ValueError: still a parse error
    for deep in ("[" * 100_000, "[" * 100_000 + "]" * 100_000):
        assert error(deep) == {"code": rpc.PARSE_ERROR, "id": None,
                               "message": "parse error: the JSON is nested too deeply"}
    assert error("[]")["code"] == rpc.INVALID_REQUEST  # batches are refused
    assert error({"jsonrpc": "2.0", "id": [1], "method": "echo"})["code"] == rpc.INVALID_REQUEST
    assert error({"id": 3, "method": "echo"}) == {
        "code": rpc.INVALID_REQUEST, "message": "invalid request", "id": 3,
        "data": {"hint": 'a request needs "jsonrpc": "2.0" and a "method" string'}}
    assert error({"jsonrpc": "2.0", "id": 4, "method": 7})["code"] == rpc.INVALID_REQUEST
    assert error(_req("nope"))["code"] == rpc.METHOD_NOT_FOUND
    forbidden = error(_req("secret"), "cli:claude")
    assert forbidden["code"] == rpc.FORBIDDEN and forbidden["message"] == "cli:claude may not call secret"
    for params in ({}, {"text": 5}, {"text": "a", "bogus": 1}, {"text": "a", "actor": "user"}, ["a"]):
        e = error(_req("echo", params))
        assert e["code"] == rpc.INVALID_PARAMS, params
    assert "text" in error(_req("echo", {}))["data"]["hint"]  # says which parameter is wrong
    assert error(_req("engine")) == {"code": rpc.ENGINE_ERROR, "message": "no such artifact: abc123",
                                     "data": {"hint": "use an artifact id"}, "id": 1}
    assert error(_req("custom")) == {"code": rpc.INVALID_PARAMS, "message": "give either path or data",
                                     "id": 1}
    bug = error(_req("bug"))
    assert bug["code"] == rpc.INTERNAL_ERROR and "ZeroDivisionError: oops" in bug["message"]
    assert error(_req("unencodable"))["code"] == rpc.INTERNAL_ERROR


def test_notification_frame():
    assert json.loads(rpc.notification("turn.finished", {"reason": "done"})) == {
        "jsonrpc": "2.0", "method": "turn.finished", "params": {"reason": "done"}}


# --- CoreApp ------------------------------------------------------------------------------------


class Failed(Exception):
    def __init__(self, error: dict):
        super().__init__(error["message"])
        self.code, self.message, self.data = error["code"], error["message"], error.get("data")


class Client:
    """One connection's view of the app: events in, JSON-RPC calls out."""

    def __init__(self, app: CoreApp, actor: str = "user"):
        self.app, self.actor, self.events, self._ids = app, actor, [], 0
        self._cond = asyncio.Condition()
        self.unsubscribe = app.subscribe(self._on_event)

    async def _on_event(self, msg: str) -> None:
        async with self._cond:
            self.events.append(json.loads(msg))
            self._cond.notify_all()

    async def call(self, method: str, **params):
        self._ids += 1
        id_ = self._ids  # calls may overlap: each one checks its own id
        frame = json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
        reply = json.loads(await self.app.dispatcher.handle(frame, self.actor))
        assert reply["id"] == id_
        if "error" in reply:
            raise Failed(reply["error"])
        return reply["result"]

    async def event(self, method: str, match=lambda params: True, timeout: float = 10.0) -> dict:
        """The params of the first `method` event that `match`es, waiting for it if it hasn't come yet."""
        def found():
            hits = (e["params"] for e in self.events if e["method"] == method and match(e["params"]))
            return next(hits, None)

        async with self._cond:
            await asyncio.wait_for(self._cond.wait_for(lambda: found() is not None), timeout)
            return found()

    async def waiting(self, match=lambda step: True) -> str:
        """The id of the first step announced by approval.needed that `match`es."""
        return (await self.event("approval.needed", lambda p: match(p["step"])))["step"]["id"]

    async def count(self, method: str, n: int, timeout: float = 10.0) -> None:
        """Wait until `method` has arrived n times."""
        async with self._cond:
            await asyncio.wait_for(self._cond.wait_for(lambda: self.methods().count(method) >= n), timeout)

    def methods(self) -> list[str]:
        return [e["method"] for e in self.events]


def in_process(**limits) -> InProcessExecutor:
    return InProcessExecutor()


def run(body, settings: Settings | None = None, factory=in_process):
    async def main():
        app = CoreApp(settings or Settings(), executor_factory=factory)
        try:
            return await asyncio.wait_for(body(app), 60)
        finally:
            await app.close()

    return asyncio.run(main())


async def imported(c: Client, data: bytes = LINCOLN, name: str = "lincoln.png") -> str:
    r = await c.call("artifacts.import", data=base64.b64encode(data).decode(), name=name)
    return r["working"]["id"]


async def idle(c: Client) -> dict:
    """The snapshot once no turn is running (a stopped turn finishes its cleanup after its last event)."""
    for _ in range(500):
        snap = await c.call("session.get")
        if not snap["turn_running"]:
            return snap
        await asyncio.sleep(0.01)
    raise AssertionError("the turn never ended")


def script(env: Path, replies: list[dict]) -> str:
    path = env / "script.json"
    path.write_text(json.dumps(replies), encoding="utf-8")
    return str(path)


def test_methods_are_the_protocol(env):
    async def body(app):
        assert app.dispatcher.names() == METHODS

    run(body)


def test_import_run_get_and_events(env, monkeypatch):
    async def body(app):
        c = Client(app)
        trump = await c.call("artifacts.import", path=str(TRUMP))
        # a small upright PNG is its own working copy, stored once; the label is the file name's stem + _work
        assert trump["working"] == trump["original"] and trump["working"]["label"] == "trump_work"
        assert trump["original"]["width"] == 474
        buf = io.BytesIO()
        with Image.open(TRUMP) as im:
            im.convert("RGB").save(buf, "JPEG")
        photo = await c.call("artifacts.import", data=base64.b64encode(buf.getvalue()).decode(), name="photo.jpg")
        assert (photo["working"]["label"], photo["original"]["label"]) == ("photo_work", "photo")
        assert (photo["working"]["format"], photo["original"]["format"]) == ("PNG", "JPEG")
        assert photo["working"]["original_id"] == photo["original"]["id"]
        for missing in (env / "nope.png", env):  # a missing file, a folder: clean errors
            with pytest.raises(Failed) as e:
                await c.call("artifacts.import", path=str(missing))
            assert e.value.code == rpc.ENGINE_ERROR and e.value.message.startswith("can't read")
        with monkeypatch.context() as m, pytest.raises(Failed) as e:  # refused before it is read
            m.setattr(server_app, "MAX_IMPORT_BYTES", 1000)
            await c.call("artifacts.import", path=str(TRUMP))
        assert e.value.message == "trump.png is too big to import"
        with pytest.raises(Failed) as e:
            await c.call("artifacts.import", path="trump.png")
        assert "absolute" in e.value.message
        with pytest.raises(Failed) as e:
            await c.call("artifacts.import", path=str(TRUMP), data="AAAA")
        assert e.value.code == rpc.INVALID_PARAMS
        with pytest.raises(Failed) as e:
            await c.call("artifacts.import", data="not base64!")
        assert e.value.code == rpc.INVALID_PARAMS
        lincoln = await imported(c)

        step = await c.call("tools.run", tool="cutout",
                            params={"image": lincoln[:8], "box": HEAD, "no_ai": True})
        assert step["status"] == "done" and step["actor"] == "user" and step["params"]["image"] == lincoln
        out = step["outputs"][0]
        await c.event("step.started", lambda p: p["step"]["id"] == step["id"])
        finished = await c.event("step.finished", lambda p: p["step"]["id"] == step["id"])
        assert [a["id"] for a in finished["artifacts"]] == [out]

        got = await c.call("artifacts.get", id=out)
        assert base64.b64decode(got["data"]) == app.session.artifacts.data(out)
        assert got["mime"] == "image/png" and (got["meta"]["width"], got["meta"]["height"]) == (250, 280)
        thumb = await c.call("artifacts.get", id=out[:6], max_px=64)
        with Image.open(io.BytesIO(base64.b64decode(thumb["data"]))) as im:
            assert thumb["mime"] == "image/png" and im.format == "PNG" and im.size == (57, 64)
        with pytest.raises(Failed) as e:
            await c.call("artifacts.get", id="ffffff")
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "no such artifact: ffffff"
        with pytest.raises(Failed) as e:
            await c.call("artifacts.get", id=out, max_px=5)
        assert e.value.code == rpc.INVALID_PARAMS

        # an engine failure is a failed step, not an RPC error; bad parameters are an RPC error
        failed = await c.call("tools.run", tool="cutout",
                              params={"image": lincoln, "box": [900, 900, 950, 950], "no_ai": True})
        assert failed["status"] == "error" and "empty" in failed["error"]["message"]
        await c.event("step.failed", lambda p: p["step"]["id"] == failed["id"])
        with pytest.raises(Failed) as e:
            await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": "big"})
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "bad parameters for cutout"

        snap = await c.call("session.get")
        assert [s["status"] for s in snap["steps"]] == ["done", "error"]
        assert snap["schema"] == 1 and snap["id"] == app.session.data.id and snap["path"] is None
        assert snap["turn_running"] is False and snap["pending_approvals"] == []

    run(body)


def test_untrusted_actor_rules_and_approvals(env):
    async def body(app):
        user, cli = Client(app), Client(app, "cli:claude")
        lincoln = await imported(user)
        for method, params in (("session.get", {}), ("session.new", {}), ("session.restore", {}),
                               ("settings.set", {"values": {}}),
                               ("artifacts.import", {"path": str(TRUMP)}),
                               ("export", {"artifact_id": lincoln}),
                               ("approval.respond", {"step_id": "s1", "decision": "approve"}),
                               ("chat.send", {"text": "hi"}), ("steps.delete", {"step_id": "s1"})):
            with pytest.raises(Failed) as e:
                await cli.call(method, **params)
            assert e.value.code == rpc.FORBIDDEN, method

        cli_tools = {t["name"]: t for t in await cli.call("tools.list")}
        user_tools = {t["name"]: t for t in await user.call("tools.list")}
        assert "clipboard" not in cli_tools["fetch"]["schema"]["properties"]
        assert "clipboard" in user_tools["fetch"]["schema"]["properties"]
        assert cli_tools["export"]["writes_files"] and not cli_tools["export"]["mutates"]
        assert cli_tools["find"]["read_only"] and cli_tools["fetch"]["network"]
        assert set(cli_tools["cutout"]) == {"name", "summary", "description", "category", "mutates",
                                            "network", "read_only", "writes_files", "schema"}

        with pytest.raises(Failed) as e:  # a path is never an artifact id
            await cli.call("tools.run", tool="info", params={"image": str(TRUMP)})
        assert e.value.message == f"no such artifact: {TRUMP}"
        with pytest.raises(Failed) as e:
            await cli.call("tools.run", tool="fetch", params={"clipboard": True})
        assert e.value.message == "fetch: clipboard can only be set by the user"

        # ask_changes: read-only tools run at once, the rest wait for the user
        info = await cli.call("tools.run", tool="info", params={"image": lincoln[:8]})
        assert info["status"] == "done" and info["actor"] == "cli:claude"
        waiting = asyncio.create_task(cli.call("tools.run", tool="cutout", params={
            "image": lincoln, "box": [0, 0, 100, 100], "no_ai": True}))
        sid = await user.waiting()
        assert (await user.call("session.get"))["pending_approvals"] == [sid]
        for bad, code in (({"decision": "edit", "params": {"image": lincoln, "box": "x"}}, rpc.ENGINE_ERROR),
                          ({"decision": "edit"}, rpc.ENGINE_ERROR),
                          ({"decision": "maybe"}, rpc.INVALID_PARAMS)):
            with pytest.raises(Failed) as e:  # a bad answer is refused and the step keeps waiting
                await user.call("approval.respond", step_id=sid, **bad)
            assert e.value.code == code, bad
        with pytest.raises(Failed) as e:  # an image the session doesn't have: refused before anything runs
            await user.call("approval.respond", step_id=sid, decision="edit",
                            params={"image": "ffffff", "box": [10, 10, 60, 90], "no_ai": True})
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "no such artifact: ffffff"
        assert (await user.call("session.get"))["pending_approvals"] == [sid]
        assert app.session.step(sid).status == "proposed" and not waiting.done()
        await user.call("approval.respond", step_id=sid, decision="edit",
                        params={"image": lincoln, "box": [10, 10, 60, 90], "no_ai": True})
        step = await waiting
        assert step["status"] == "done" and step["params"]["box"] == [10, 10, 60, 90]
        assert app.session.artifacts.meta[step["outputs"][0]].width == 50

        rejected = asyncio.create_task(cli.call("tools.run", tool="filter",
                                                params={"image": lincoln, "names": ["invert"]}))
        sid = await user.waiting(lambda step: step["tool"] == "filter")
        await user.call("approval.respond", step_id=sid, decision="reject", note="not that")
        assert (await rejected)["status"] == "rejected"

        # a CLI agent that stops waiting (Task 13 cancels a closed connection's requests) leaves no step waiting
        gone = asyncio.create_task(cli.call("tools.run", tool="filter",
                                            params={"image": lincoln, "names": ["emboss"]}))
        sid = await user.waiting(lambda step: step["params"].get("names") == ["emboss"])
        gone.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gone
        assert app.session.step(sid).status == "rejected"
        assert (await user.call("session.get"))["pending_approvals"] == []
        with pytest.raises(Failed) as e:  # nothing is waiting for that step any more
            await user.call("approval.respond", step_id=sid, decision="approve")
        assert e.value.code == rpc.ENGINE_ERROR
        assert "proposed" not in {s.status for s in app.session.data.steps}

    run(body)


def test_an_edit_the_session_refuses_rejects_the_cli_step(env):
    """The backstop behind approval.respond's own checks: an edit that Session.run refuses (it does so before
    it changes the step) rejects the step in the same locked call, so it never stays proposed with nothing
    waiting for it."""
    session = Session.new(executor=InProcessExecutor())
    lincoln = session.import_image(LINCOLN, "lincoln.png").id
    step = session.propose("cutout", {"image": lincoln, "box": HEAD, "no_ai": True}, "cli:claude")
    refused = CoreApp._run_or_reject(session, step.id, {"image": "ffffff", "box": HEAD, "no_ai": True})
    assert refused.status == "rejected"
    assert refused.result_text == ("rejected by user: the edited parameters were refused: "
                                   "no such artifact: ffffff")
    with pytest.raises(EngineError):  # on its own params there is nothing to fall back to
        CoreApp._run_or_reject(session, step.id, None)
    ok = session.propose("cutout", {"image": lincoln, "box": HEAD, "no_ai": True}, "cli:claude")
    assert CoreApp._run_or_reject(session, ok.id, None).status == "done"
    assert CoreApp._settle(session, ok.id, "too late").status == "done"  # a step that ran stays as it is
    assert [s.status for s in session.data.steps] == ["rejected", "done"]


def test_cli_calls_follow_the_sessions_approval_mode(env):
    """Spec 7, "the same gate applies to CLI agents": whether a CLI agent's call waits is decided by the open
    session's mode (session.data.approval_mode) when the call is made, not by the settings' mode for new
    sessions. A switch applies from the next call, and an opened project brings its own mode."""
    async def body(app):
        user, cli = Client(app), Client(app, "cli:gemini")
        lincoln = await imported(user)
        assert (await user.call("session.get"))["approval_mode"] == "ask_all"  # a new session: the settings'
        info = asyncio.create_task(cli.call("tools.run", tool="info", params={"image": lincoln}))
        sid = await user.waiting(lambda step: step["tool"] == "info")  # ask_all: even a read-only tool waits
        await user.call("approval.respond", step_id=sid, decision="approve")
        assert (await info)["status"] == "done"

        await user.call("session.set_approval_mode", mode="auto")
        cut = await asyncio.wait_for(cli.call("tools.run", tool="cutout", params={
            "image": lincoln, "box": HEAD, "no_ai": True}), 10)  # auto: it runs without asking
        assert cut["status"] == "done" and cut["actor"] == "cli:gemini"
        assert app.settings.approval_mode == "ask_all"  # the session's mode decided, not the settings'
        saved = await user.call("session.save_as", path=str(env / "auto.badshop"))

        await user.call("session.set_approval_mode", mode="ask_changes")
        assert (await cli.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"
        filtered = asyncio.create_task(cli.call("tools.run", tool="filter",
                                                params={"image": lincoln, "names": ["invert"]}))
        sid = await user.waiting(lambda step: step["tool"] == "filter")  # ask_changes: a change waits
        await user.call("approval.respond", step_id=sid, decision="reject", note="not now")
        assert (await filtered)["status"] == "rejected"

        opened = await user.call("session.open", path=saved["path"])  # saved while the mode was auto
        assert opened["approval_mode"] == "auto"
        again = await asyncio.wait_for(cli.call("tools.run", tool="filter", params={
            "image": lincoln, "names": ["invert"]}), 10)
        assert again["status"] == "done" and again["actor"] == "cli:gemini"
        # only the two calls their session's mode held back ever waited
        assert [e["params"]["step"]["tool"] for e in user.events if e["method"] == "approval.needed"] == [
            "info", "filter"]

    run(body, Settings(approval_mode="ask_all"))


def test_edit_replays_the_later_steps(env):
    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        cut = await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        pasted = await c.call("tools.run", tool="paste", params={"base": lincoln, "piece": cut["outputs"][0],
                                                                  "fit_box": [0, 0, 200, 200]})
        edited = await c.call("steps.edit", step_id=cut["id"],
                              params={"image": lincoln, "box": [100, 50, 300, 300], "no_ai": True})
        assert edited == {"stale": [cut["id"], pasted["id"]]}
        assert (await c.event("step.stale")) == {"step_ids": [cut["id"], pasted["id"]]}
        # auto_replay: the replay runs by itself after the edit returns
        await c.event("step.finished", lambda p: p["step"]["id"] == pasted["id"]
                      and p["step"]["outputs"] != pasted["outputs"])
        steps = (await c.call("session.get"))["steps"]
        assert [s["status"] for s in steps] == ["done", "done"]
        assert steps[1]["params"]["piece"] == steps[0]["outputs"][0] != cut["outputs"][0]

        await c.call("settings.set", values={"auto_replay": False})
        await c.call("steps.edit", step_id=cut["id"], params={"image": lincoln, "box": [100, 50, 250, 250],
                                                              "no_ai": True})
        assert [s["status"] for s in (await c.call("session.get"))["steps"]] == ["stale", "stale"]
        replayed = await c.call("steps.replay_from", step_id=cut["id"])
        assert [(s["id"], s["status"]) for s in replayed] == [(cut["id"], "done"), (pasted["id"], "done")]

        with pytest.raises(Failed) as e:  # only the last step can go (spec 7)
            await c.call("steps.delete", step_id=cut["id"])
        assert e.value.code == rpc.ENGINE_ERROR
        assert await c.call("steps.delete", step_id=pasted["id"]) == {"deleted": pasted["id"]}
        assert [s["id"] for s in (await c.call("session.get"))["steps"]] == [cut["id"]]
        # the session's step.deleted reaches the client (ruling R7); the refused delete sent none
        assert await c.event("step.deleted") == {"step_id": pasted["id"]}
        assert [e["params"] for e in c.events if e["method"] == "step.deleted"] == [{"step_id": pasted["id"]}]

    run(body)


def test_project_files_export_and_modes(env):
    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        cut = await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        mode = await c.call("session.set_approval_mode", mode="ask_all")
        assert mode["approval_mode"] == "ask_all"
        with pytest.raises(Failed) as e:
            await c.call("session.set_approval_mode", mode="yolo")
        assert e.value.code == rpc.INVALID_PARAMS

        with pytest.raises(Failed) as e:
            await c.call("session.save")
        assert e.value.message == "this session has no project file yet"
        with pytest.raises(Failed) as e:
            await c.call("session.save_as", path="relative.badshop")
        assert "absolute" in e.value.message
        saved = await c.call("session.save_as", path=str(env / "one.badshop"))
        assert Path(saved["path"]).is_file() and (await c.call("session.get"))["path"] == saved["path"]
        assert await c.call("session.save") == saved
        recipe = await c.call("session.export_recipe", path=str(env / "recipe.json"))
        assert json.loads(Path(recipe["path"]).read_text(encoding="utf-8"))["steps"]

        exported = await c.call("export", artifact_id=cut["outputs"][0][:8], name="head")
        assert exported == {"path": str(env / "out" / "head.png")}
        assert (env / "out" / "head.png").read_bytes() == app.session.artifacts.data(cut["outputs"][0])
        with pytest.raises(Failed) as e:
            await c.call("export", artifact_id="ffffff")
        assert e.value.message == "no such artifact: ffffff"

        # a file that isn't a project is refused, and the open session is untouched
        before = await c.call("session.get")
        (env / "junk.badshop").write_bytes(b"not a zip")
        for bad in (env / "junk.badshop", env / "missing.badshop"):
            with pytest.raises(Failed) as e:
                await c.call("session.open", path=str(bad))
            assert e.value.code == rpc.ENGINE_ERROR
        assert await c.call("session.get") == before

        new = await c.call("session.new", name="second")
        assert new["name"] == "second" and new["steps"] == [] and new["path"] is None
        assert new["approval_mode"] == "ask_changes"  # new sessions start in the settings' mode
        with pytest.raises(Failed) as e:
            await c.call("session.new", name="")
        assert e.value.code == rpc.INVALID_PARAMS
        opened = await c.call("session.open", path=saved["path"])
        assert opened["path"] == saved["path"] and opened["approval_mode"] == "ask_all"
        assert [s["id"] for s in opened["steps"]] == [cut["id"]]
        got = await c.call("artifacts.get", id=cut["outputs"][0])
        assert base64.b64decode(got["data"]) == (env / "out" / "head.png").read_bytes()

    run(body)


def test_the_next_launch_offers_the_last_autosave(env):
    """Spec 9 and 10: after a crash (or a quit) the next launch offers to restore the last run's autosave.
    CoreApp moves it aside as it starts (project.claim_autosave), so the new run's own first change, which
    autosaves, can't overwrite it."""
    async def first_run(app):
        c = Client(app)
        assert (await c.call("session.get"))["restorable"] is None  # a first launch has nothing to offer
        with pytest.raises(Failed) as e:
            await c.call("session.restore")
        assert e.value.code == rpc.ENGINE_ERROR
        assert e.value.message == "there is no autosaved session to restore"
        lincoln = await imported(c)
        await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        assert project.find_autosave() == project.autosave_path()  # saved after the step, not at close

    async def next_run(app):
        c = Client(app)
        snap = await c.call("session.get")
        assert snap["steps"] == [] and snap["restorable"] is not None
        offered = Path(snap["restorable"])
        assert offered.read_bytes() == last_run and project.find_autosave() is None  # moved aside
        await imported(c, TRUMP.read_bytes(), "trump.png")  # this run's first change autosaves...
        assert project.find_autosave() is not None
        assert offered.read_bytes() == last_run  # ...and the offer survives it
        assert (await c.call("session.get"))["restorable"] == str(offered)

        restored = await c.call("session.restore")
        assert [s["tool"] for s in restored["steps"]] == ["cutout"]
        assert restored["path"] is None  # the autosave is not the user's project file
        assert restored["restorable"] is None  # the offer is used up
        got = await c.call("artifacts.get", id=restored["steps"][0]["outputs"][0])
        assert (got["meta"]["width"], got["meta"]["height"]) == (250, 280)
        with pytest.raises(Failed) as e:
            await c.call("session.save")
        assert e.value.message == "this session has no project file yet"
        with pytest.raises(Failed) as e:
            await c.call("session.restore")
        assert e.value.message == "there is no autosaved session to restore"
        # from now on this run's autosave holds the restored session
        autosaved = project.open_project(project.autosave_path(), executor=InProcessExecutor())
        assert [s.tool for s in autosaved.data.steps] == ["cutout"]
        # opening a file in the autosave folder by hand doesn't make it the project file either
        assert (await c.call("session.open", path=str(offered)))["path"] is None

    run(first_run)
    last_run = project.autosave_path().read_bytes()
    run(next_run)


def test_chat_turn_with_an_approval(env):
    async def body(app):
        c = Client(app)
        with pytest.raises(Failed) as e:
            await c.call("chat.send", text="hi")
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "no model provider is set up yet"
        await c.call("settings.set", values={"fake_provider_script": str(env / "missing.json")})
        with pytest.raises(Failed) as e:
            await c.call("chat.send", text="hi")
        assert e.value.code == rpc.ENGINE_ERROR
        assert e.value.message.startswith("can't read the fake provider script")
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "Let me measure it.",
             "tool_calls": [{"name": "info", "arguments": {"image": lincoln[:8]}}]},
            {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": lincoln[:8], "box": HEAD,
                                                                          "no_ai": True}}]},
            {"text": "Here is his head.", "tool_calls": []},
        ])})
        with pytest.raises(Failed) as e:  # a bad attachment fails before any turn starts
            await c.call("chat.send", text="crop", attachments=["ffffff"])
        assert e.value.message == "no such artifact: ffffff"
        started = await c.call("chat.send", text="crop lincoln's head", attachments=[lincoln[:8]])
        assert started == {"started": True}

        needed = await c.event("approval.needed")
        assert needed["step"]["tool"] == "cutout" and needed["step"]["actor"] == "agent:fake"
        snap = await c.call("session.get")
        assert snap["turn_running"] and snap["pending_approvals"] == [needed["step"]["id"]]
        for method, params in (("chat.send", {"text": "again"}), ("session.new", {}), ("session.restore", {}),
                               ("session.open", {"path": str(env / "other.badshop")})):
            with pytest.raises(Failed) as e:  # one turn at a time; the session stays while it runs
                await c.call(method, **params)
            assert e.value.message == "the agent is still working", method
        await c.call("approval.respond", step_id=needed["step"]["id"], decision="edit",
                     params={"image": lincoln, "box": [100, 50, 300, 300], "no_ai": True})

        assert await c.event("turn.finished") == {"reason": "done"}
        await idle(c)
        steps = app.session.data.steps
        assert [(s.tool, s.status, s.actor) for s in steps] == [("info", "done", "agent:fake"),
                                                                ("cutout", "done", "agent:fake")]
        assert steps[1].params["box"] == [100, 50, 300, 300]
        streamed = "".join(e["params"]["text"] for e in c.events if e["method"] == "message.delta")
        assert "Let me measure it." in streamed and "Here is his head." in streamed
        m = c.methods()
        assert m.index("turn.started") < m.index("approval.needed") < m.index("approval.resolved") < \
            m.index("turn.finished")

    run(body)


def test_switching_the_approval_mode_mid_turn(env):
    """session.set_approval_mode while a turn runs: the turn follows the new mode from its next tool call
    (run_turn reads cfg.approval_mode at every call, and CoreApp assigns it), whether the switch asks for
    more approvals or for fewer. The call already waiting keeps waiting."""
    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": lincoln, "box": HEAD,
                                                                          "no_ai": True}}]},
            {"text": "", "tool_calls": [{"name": "info", "arguments": {"image": lincoln}}]},
            {"text": "", "tool_calls": [{"name": "filter", "arguments": {"image": lincoln,
                                                                          "names": ["invert"]}}]},
            {"text": "All done.", "tool_calls": []},
        ])})
        await c.call("chat.send", text="go")
        cut = await c.waiting(lambda step: step["tool"] == "cutout")  # ask_changes: a change waits
        snap = await c.call("session.set_approval_mode", mode="ask_all")
        assert snap["approval_mode"] == "ask_all" and snap["turn_running"]
        assert snap["pending_approvals"] == [cut]  # the call already waiting keeps waiting
        await c.call("approval.respond", step_id=cut, decision="approve")
        info = await c.waiting(lambda step: step["tool"] == "info")  # ask_all: now a read-only tool waits too
        await c.call("session.set_approval_mode", mode="auto")
        await c.call("approval.respond", step_id=info, decision="approve")
        assert await c.event("turn.finished") == {"reason": "done"}  # auto: the filter ran without asking
        snap = await idle(c)
        assert [(s["tool"], s["status"]) for s in snap["steps"]] == [("cutout", "done"), ("info", "done"),
                                                                     ("filter", "done")]
        assert [e["params"]["step"]["tool"] for e in c.events if e["method"] == "approval.needed"] == [
            "cutout", "info"]
        # the switch is the session's: the settings' mode for new sessions is unchanged
        assert snap["approval_mode"] == "auto" and app.settings.approval_mode == "ask_changes"

    run(body)


def test_stop_and_client_gone(env):
    """Review focus 1 at the app level: Stop ends the chat's turn and leaves a CLI agent's call waiting;
    when the UI goes away mid-turn, the turn stops cleanly, every pending approval (the agent's and a CLI
    agent's) is rejected, and the core keeps serving."""
    async def body(app):
        c, cli = Client(app), Client(app, "cli:codex")
        lincoln = await imported(c)
        cut = {"name": "cutout", "arguments": {"image": lincoln, "box": [0, 0, 100, 100], "no_ai": True}}
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "one", "tool_calls": [cut]}, {"text": "two", "tool_calls": [cut]}])})

        await c.call("chat.send", text="go")
        first = await c.waiting()
        waiting = asyncio.create_task(cli.call("tools.run", tool="filter",
                                               params={"image": lincoln, "names": ["invert"]}))
        third = await c.waiting(lambda step: step["actor"] == "cli:codex")
        assert (await c.call("session.get"))["pending_approvals"] == [first, third]
        assert await c.call("chat.stop") == {"stopped": True}
        assert await c.event("turn.finished") == {"reason": "stopped"}
        assert app.session.step(first).status == "rejected"
        # Stop is about the chat: the CLI agent's call still waits for the user
        assert (await c.call("session.get"))["pending_approvals"] == [third]
        assert app.session.step(third).status == "proposed" and not waiting.done()
        assert await c.call("chat.stop") == {"stopped": False}

        await c.call("chat.send", text="again")
        second = await cli.waiting(lambda step: step["actor"] == "agent:fake" and step["id"] != first)
        c.unsubscribe()
        app.on_client_gone()
        assert (await waiting)["status"] == "rejected"
        await cli.count("turn.finished", 2)
        assert [e["params"] for e in cli.events if e["method"] == "turn.finished"][-1] == {"reason": "stopped"}

        later = Client(app)  # the UI reconnects
        snap = await idle(later)
        steps = {s["id"]: s for s in snap["steps"]}
        assert [steps[i]["status"] for i in (first, second, third)] == ["rejected"] * 3
        assert steps[third]["result_text"] == "rejected by user: the user closed the app"
        assert snap["pending_approvals"] == [] and "proposed" not in {s["status"] for s in snap["steps"]}
        assert (await later.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"

    run(body)


class HangingFirstCall(InProcessExecutor):
    """The first tool call hangs until it is stopped, by its own cancel event (a turn's Stop) or by cancel()
    (or a test setting `released`); later calls run normally. Counts cancel() and close()."""

    def __init__(self):
        self.started, self.released = threading.Event(), threading.Event()
        self.calls = self.cancels = self.closes = 0
        self.stopped_by: str | None = None

    def run(self, call, cancel=None):
        self.calls += 1
        if self.calls > 1:
            return super().run(call, cancel)
        self.started.set()
        for _ in range(1000):  # up to 10 s
            if self.released.wait(0.01) or (cancel is not None and cancel.is_set()):
                self.stopped_by = "cancel()" if self.released.is_set() else "its event"
                return ToolOutcome(ok=False, error_message="stopped by the user")
        raise AssertionError("never stopped")

    def cancel(self):
        self.cancels += 1
        self.released.set()

    def close(self):
        self.closes += 1


def test_stop_while_a_tool_runs(env):
    ex = HangingFirstCall()

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("session.set_approval_mode", mode="auto")
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": lincoln, "box": HEAD,
                                                                          "no_ai": True}}]}])})
        await c.call("chat.send", text="go")
        assert await asyncio.to_thread(ex.started.wait, 10)
        assert await c.call("chat.stop") == {"stopped": True}  # returns once the tool's thread has ended
        assert ex.stopped_by == "its event" and ex.cancels == 0  # the turn's Stop reached this very call
        step = app.session.data.steps[-1]
        assert step.status == "error" and step.error.message == "stopped by the user"
        # the autosave holds the turn as it ended: the stopped call has its answer, as in memory
        transcript = app.session.data.transcript
        assert transcript[-1] == {"role": "tool", "tool_call_id": "call_1", "content": step.result_text}
        assert project.open_project(project.autosave_path()).data.transcript == transcript
        assert (await c.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"

    run(body, factory=lambda **limits: ex)
    assert ex.closes == 1  # close() closed the executor


def test_settings_apply_to_the_running_app(env):
    made: list[tuple[dict, HangingFirstCall]] = []

    def factory(**limits):
        ex = HangingFirstCall()
        ex.calls = 1  # never hang
        made.append((limits, ex))
        return ex

    async def body(app):
        c = Client(app)
        assert [limits for limits, _ in made] == [{"timeout_s": 120.0, "max_rss_mb": 3072}]
        got = await c.call("settings.set", values={"tool_timeout_s": 5, "output_dir": str(env / "elsewhere")})
        assert got["tool_timeout_s"] == 5.0 and load_settings() == Settings(**got)
        assert made[-1][0] == {"timeout_s": 5.0, "max_rss_mb": 3072}
        assert made[0][1].closes == 1 and app.session.executor is made[-1][1]
        await c.call("settings.set", values={"auto_replay": False})
        assert len(made) == 2  # unchanged limits keep the executor
        with pytest.raises(Failed) as e:
            await c.call("settings.set", values={"step_budget": 0})
        assert e.value.code == rpc.INVALID_PARAMS and "step_budget" in e.value.data["hint"]
        with pytest.raises(Failed) as e:
            await c.call("settings.set", values={"bogus": 1})
        assert e.value.code == rpc.INVALID_PARAMS
        assert (await c.call("settings.get"))["step_budget"] == 40
        lincoln = await imported(c)  # labelled lincoln_work: the working copy
        assert (await c.call("export", artifact_id=lincoln))["path"] == str(env / "elsewhere" /
                                                                            "lincoln_work.png")

    run(body, factory=factory)
    assert [ex.closes for _, ex in made] == [1, 1]


def test_no_turn_starts_while_the_session_is_being_replaced(env):
    ex = HangingFirstCall()

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [{"text": "hello"}])})
        busy = asyncio.create_task(c.call("tools.run", tool="info", params={"image": lincoln}))
        assert await asyncio.to_thread(ex.started.wait, 10)  # the user's tool holds the lock
        new = asyncio.create_task(c.call("session.new", name="next"))
        await asyncio.sleep(0)  # session.new runs up to the lock and waits there
        with pytest.raises(Failed) as e:  # a turn started now would run on the session being replaced
            await c.call("chat.send", text="hi")
        assert e.value.code == rpc.ENGINE_ERROR and e.value.message == "the session is being replaced"
        ex.released.set()
        assert (await busy)["status"] == "error"
        assert (await new)["name"] == "next"
        assert await c.call("chat.send", text="hi") == {"started": True}
        assert await c.event("turn.finished") == {"reason": "done"}
        assert [m["role"] for m in (await idle(c))["messages"]] == ["user", "assistant"]

    run(body, factory=lambda **limits: ex)


def test_failures_are_reported_and_the_core_keeps_serving(env, monkeypatch):
    async def broken_turn(*args, **kw):
        raise RuntimeError("kaput")

    def full_disk(session):
        raise EngineError("can't save the project (disk full)")

    def broken_replay(self, step_id, **kw):
        raise EngineError("replay broke")

    async def body(app):
        c = Client(app)
        lincoln = await imported(c)
        await c.call("settings.set", values={"fake_provider_script": script(env, [{"text": "hi"}])})
        monkeypatch.setattr(server_app, "run_turn", broken_turn)
        assert await c.call("chat.send", text="hi") == {"started": True}
        assert await c.event("turn.finished") == {"reason": "error", "error": "RuntimeError: kaput"}
        assert await c.event("core.log") == {"level": "error",
                                             "message": "the agent turn failed (RuntimeError: kaput)"}
        assert (await idle(c))["turn_running"] is False

        monkeypatch.setattr(project, "autosave", full_disk)
        cut = await c.call("tools.run", tool="cutout", params={"image": lincoln, "box": HEAD, "no_ai": True})
        assert cut["status"] == "done"  # the step is fine; its autosave failed, and that is reported
        assert await c.event("core.log", lambda p: p["level"] == "warning") == {
            "level": "warning", "message": "autosave failed: can't save the project (disk full)"}

        monkeypatch.setattr(Session, "replay_from", broken_replay)
        await c.call("steps.edit", step_id=cut["id"],
                     params={"image": lincoln, "box": [100, 50, 300, 300], "no_ai": True})
        assert await c.event("core.log", lambda p: p["message"].startswith("replay")) == {
            "level": "warning", "message": "replay failed: replay broke"}
        assert (await c.call("tools.run", tool="info", params={"image": lincoln}))["status"] == "done"

    run(body)


def test_assets_status_and_download_progress(env, monkeypatch):
    def fake_download(name: str) -> Path:  # what cached() does: report each chunk to assets.PROGRESS
        assets.PROGRESS(name, 5, 10)
        assets.PROGRESS(name, 10, 10)
        return env / "data" / name

    monkeypatch.setattr(manifest, "download", fake_download)
    before = assets.PROGRESS

    async def body(app):
        c = Client(app)
        status = await c.call("assets.status")
        assert status and all(set(a) == {"name", "label", "approx_mb", "present"} for a in status)
        name = status[0]["name"]
        assert await c.call("assets.download", name=name) == {"path": str(env / "data" / name)}
        await c.event("asset.progress", lambda p: p["done"] == 10)
        assert [e["params"] for e in c.events if e["method"] == "asset.progress"] == [
            {"name": name, "done": 5, "total": 10}, {"name": name, "done": 10, "total": 10}]

    run(body)
    assert assets.PROGRESS is before  # close() put the previous listener back


def test_close_stops_a_waiting_turn(env):
    async def main():
        app = CoreApp(Settings(), executor_factory=in_process)
        c = Client(app)
        lincoln = await imported(c)
        cut = {"name": "cutout", "arguments": {"image": lincoln, "no_ai": True}}
        await c.call("settings.set", values={"fake_provider_script": script(env, [
            {"text": "", "tool_calls": [cut]}])})
        await c.call("chat.send", text="go")
        sid = await c.waiting()
        app.on_client_gone()  # the window closes and the app quits at once: two stops overlap
        await app.close()
        await app.close()  # idempotent
        assert app.session.step(sid).status == "rejected"
        assert "turn.finished" in c.methods()
        assert project.find_autosave() is not None

    asyncio.run(main())
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_server_app.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'badshop.server'`.

- [ ] **Step 3: Add the runtime dependencies**

Run: `cd core && uv add "websockets>=15,<17" "psutil>=6"`
Expected: Task 10 already added `psutil>=6`, so uv keeps that line as it is and appends `websockets`, and `core/uv.lock` gains `websockets`. The `dependencies` list in `core/pyproject.toml` now ends:
```toml
    "platformdirs>=4",
    "psutil>=6",
    "websockets>=15,<17",
]
```
Then `cd core && uv lock --check` passes.

- [ ] **Step 4: Implement the settings**

`core/src/badshop/server/__init__.py`:
```python
"""The local API: settings, the JSON-RPC dispatcher and the app behind it (spec 5.6, 7).

The WebSocket transport and the entry point live in ws.py and main.py (Task 13)."""
```

`core/src/badshop/server/settings.py`:
```python
"""User settings (spec 8.5, 9): one JSON file in the config dir. Keys and secrets never go in it."""

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from badshop.engine.errors import EngineError

ApprovalMode = Literal["auto", "ask_changes", "ask_all"]
FILE = "settings.json"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    approval_mode: ApprovalMode = "ask_changes"  # the mode new sessions start in
    auto_replay: bool = True  # replay the later steps as soon as the user edits one
    output_dir: str | None = None  # None: files.default_output_dir()
    step_budget: int = Field(40, ge=1, le=500)  # tool calls per agent turn
    tool_timeout_s: float = Field(120.0, ge=1, le=3600)  # wall clock per tool call
    tool_memory_mb: int = Field(3072, ge=256, le=65536)  # memory per tool call
    fake_provider_script: str | None = None  # a ScriptedProvider JSON file (tests and demos, until Plan 3)

    @field_validator("output_dir")
    @classmethod
    def _absolute(cls, v: str | None) -> str | None:
        if v is not None and not Path(v).expanduser().is_absolute():
            raise ValueError("give an absolute folder path")
        return v


def config_dir() -> Path:
    env = os.environ.get("BADSHOP_CONFIG_DIR")
    return Path(env) if env else Path(platformdirs.user_config_dir("badshop", appauthor=False))


def settings_path() -> Path:
    return config_dir() / FILE


def load_settings() -> Settings:
    """The saved settings. A missing or unreadable file gives the defaults; a value that is no longer
    valid (or a key this version doesn't know) is dropped, so a bad file never stops the core."""
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    values = {k: v for k, v in raw.items() if k in Settings.model_fields}
    try:
        return Settings.model_validate(values)
    except ValidationError as e:
        bad = {err["loc"][0] for err in e.errors() if err["loc"]}
        return Settings.model_validate({k: v for k, v in values.items() if k not in bad})


def save_settings(s: Settings) -> None:
    """Write the settings atomically: a temp file in the same folder, then os.replace."""
    path = settings_path()
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=FILE + ".", suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(s.model_dump_json(indent=2) + "\n")
        os.replace(tmp, path)
    except OSError as e:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        raise EngineError(f"can't save the settings ({e})",
                          hint=f"check that {path.parent} is writable") from None
```

- [ ] **Step 5: Implement the JSON-RPC dispatcher**

`core/src/badshop/server/rpc.py`:
```python
"""JSON-RPC 2.0 (one request object per text frame; batches are refused) routed to async handlers.

A handler is `async def handler(actor: str, **params) -> result`. Its keyword parameters, with their
annotations and defaults, are the method's parameter schema: the dispatcher validates `params` against
them first, so a missing, unknown or mistyped parameter is a clean INVALID_PARAMS error and the
handler never runs."""

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from badshop.engine.errors import EngineError
from badshop.tools.runner import explain, is_trusted

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
ENGINE_ERROR = -32000  # an EngineError; data {"hint": ...}
FORBIDDEN = -32001  # this actor may not call this method

ACTORS = ("user", "any")

log = logging.getLogger("badshop.server")

Handler = Callable[..., Awaitable[Any]]


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def notification(method: str, params: dict) -> str:
    """A server event: a JSON-RPC notification (no id)."""
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": params})


def _error(id_: Any, e: RpcError) -> str:
    err: dict[str, Any] = {"code": e.code, "message": e.message}
    if e.data is not None:
        err["data"] = e.data
    return json.dumps({"jsonrpc": "2.0", "id": id_, "error": err})


def _valid_id(id_: Any) -> bool:
    return id_ is None or isinstance(id_, str) or (isinstance(id_, int) and not isinstance(id_, bool))


def params_model(name: str, fn: Handler) -> type[BaseModel]:
    """The handler's parameters after `actor`, as a pydantic model that refuses unknown keys."""
    fields: dict[str, Any] = {}
    for p in list(inspect.signature(fn, eval_str=True).parameters.values())[1:]:
        annotation = Any if p.annotation is inspect.Parameter.empty else p.annotation
        fields[p.name] = (annotation, ... if p.default is inspect.Parameter.empty else p.default)
    return create_model(f"Params_{name.replace('.', '_')}",
                        __config__=ConfigDict(extra="forbid", allow_inf_nan=False), **fields)


class Dispatcher:
    def __init__(self) -> None:
        self._methods: dict[str, tuple[Handler, type[BaseModel], str]] = {}

    def method(self, name: str, *, actors: str = "user") -> Callable[[Handler], Handler]:
        """Register an async handler. actors="user": only the trusted user may call it; "any": every
        connected actor may (the handler gets the actor and applies its own rules)."""
        if actors not in ACTORS:
            raise ValueError(f"actors must be one of {ACTORS}, not {actors!r}")
        if name in self._methods:
            raise ValueError(f"method {name!r} is already registered")

        def register(fn: Handler) -> Handler:
            self._methods[name] = (fn, params_model(name, fn), actors)
            return fn

        return register

    def names(self) -> list[str]:
        return sorted(self._methods)

    async def handle(self, raw: str, actor: str) -> str | None:
        """One incoming frame -> the reply frame, or None for a notification (a request without an id).
        Calls are independent, so a transport may await several at once."""
        try:
            msg = json.loads(raw)
        except ValueError:
            return _error(None, RpcError(PARSE_ERROR, "parse error: that is not JSON"))
        except RecursionError:  # e.g. "[" * 100_000: json refuses nesting deeper than the recursion limit
            return _error(None, RpcError(PARSE_ERROR, "parse error: the JSON is nested too deeply"))
        if not isinstance(msg, dict) or not _valid_id(msg.get("id")):
            return _error(None, RpcError(INVALID_REQUEST, "invalid request",
                                         {"hint": "send one JSON-RPC 2.0 request object per message"}))
        id_, is_request = msg.get("id"), "id" in msg
        if msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(id_, RpcError(INVALID_REQUEST, "invalid request",
                                        {"hint": 'a request needs "jsonrpc": "2.0" and a "method" string'}))
        try:
            result = await self._call(msg["method"], msg.get("params", {}), actor)
            return json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}) if is_request else None
        except RpcError as e:
            if not is_request:
                log.warning("notification %s failed: %s", msg["method"], e.message)
            return _error(id_, e) if is_request else None
        except (TypeError, ValueError) as e:  # json can't encode the result: a bug in the handler
            log.exception("%s returned a result that isn't JSON", msg["method"])
            return _error(id_, RpcError(INTERNAL_ERROR, f"internal error ({e})")) if is_request else None

    async def _call(self, method: str, params: Any, actor: str) -> Any:
        entry = self._methods.get(method)
        if entry is None:
            raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")
        fn, model, actors = entry
        if actors == "user" and not is_trusted(actor):
            raise RpcError(FORBIDDEN, f"{actor} may not call {method}",
                           {"hint": "only the user can manage sessions, files and settings"})
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, f"params for {method} must be an object")
        try:
            checked = model.model_validate(params)
        except ValidationError as e:
            raise RpcError(INVALID_PARAMS, f"invalid params for {method}", {"hint": explain(e)}) from None
        try:
            return await fn(actor, **{name: getattr(checked, name) for name in type(checked).model_fields})
        except RpcError:
            raise
        except EngineError as e:
            raise RpcError(ENGINE_ERROR, e.message, {"hint": e.hint}) from None
        except Exception as e:
            log.exception("%s failed", method)
            raise RpcError(INTERNAL_ERROR, f"internal error in {method} ({type(e).__name__}: {e})",
                           {"hint": "this is a bug in badshop; the session is unaffected"}) from None
```

- [ ] **Step 6: Implement CoreApp**

`core/src/badshop/server/app.py`:
```python
"""CoreApp: the headless core behind the local API (spec 5.6, 7).

It owns the open session, the tool executor, the approval gate and the agent turn. JSON-RPC methods
become session calls; session changes become events for every subscriber. No sockets here:
server/ws.py (Task 13) connects clients and calls `dispatcher.handle`, `subscribe` and
`on_client_gone`."""

import asyncio
import base64
import binascii
import io
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from badshop import files
from badshop.agent import approval
from badshop.agent.approval import ApprovalGate
from badshop.agent.fake import ScriptedProvider
from badshop.agent.loop import TurnConfig, run_turn
from badshop.engine import assets, manifest
from badshop.engine.common import fit, has_alpha, to_rgb
from badshop.engine.errors import EngineError
from badshop.server import rpc
from badshop.server.rpc import INVALID_PARAMS, Dispatcher, RpcError
from badshop.server.settings import ApprovalMode, Settings, load_settings, save_settings
from badshop.session import project
from badshop.session.execution import Executor
from badshop.session.models import Step
from badshop.session.session import RUNNABLE, Session
from badshop.session.worker import WorkerExecutor
from badshop.tools import REGISTRY, registry, runner

log = logging.getLogger("badshop.server")

Send = Callable[[str], Awaitable[None]]
SessionName = Annotated[str, Field(min_length=1, max_length=200)]
MaxPx = Annotated[int, Field(ge=16, le=4096)]
Verdict = Literal["approve", "reject", "edit"]
MAX_IMPORT_BYTES = 200 * 2**20  # a picked file bigger than this is refused before it is read
NO_PROVIDER_HINT = "set fake_provider_script in the settings (or BADSHOP_FAKE_PROVIDER) to a script file"


def _user_path(path: str) -> Path:
    """A path the user picked in a file dialog. Relative paths would depend on the core's working
    folder, so they are refused."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise EngineError(f"{path} is not an absolute path", hint="pick the file with the file dialog")
    return p


def _read_import(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_IMPORT_BYTES:
            raise EngineError(f"{path.name} is too big to import",
                              hint=f"the limit is {MAX_IMPORT_BYTES // 2**20} MB; use a smaller copy")
        return path.read_bytes()
    except OSError as e:
        raise EngineError(f"can't read {path} ({e.strerror or e})",
                          hint="check that the file exists and is readable") from None


def _write_json(path: Path, value: Any) -> None:
    try:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise EngineError(f"can't write {path} ({e.strerror or e})",
                          hint="check that the folder exists and is writable") from None


def _artifact_payload(session: Session, ref: str, max_px: int | None) -> dict:
    """The artifact's stored bytes, or (with max_px) a PNG no bigger than max_px on its longest side."""
    store = session.artifacts
    aid = store.resolve(ref)
    meta = store.meta[aid]
    if max_px is None:
        data, mime = store.data(aid), meta.mime
    else:
        im = store.image(aid)
        small, _ = fit(im.convert("RGBA") if has_alpha(im) else to_rgb(im), max_px)
        buf = io.BytesIO()
        small.save(buf, "PNG")
        data, mime = buf.getvalue(), "image/png"
    return {"meta": meta.model_dump(mode="json"), "mime": mime,
            "data": base64.b64encode(data).decode("ascii")}


def _tool_entry(spec: registry.ToolSpec, trusted: bool) -> dict:
    return {"name": spec.name, "summary": spec.summary, "description": spec.description,
            "category": spec.category, "mutates": spec.mutates, "network": spec.network,
            "read_only": spec.read_only, "writes_files": spec.writes_files,
            "schema": registry.ui_schema(spec) if trusted else registry.llm_schema(spec)}


class CoreApp:
    """Create it inside the running event loop (it binds to that loop), and `await close()` when done."""

    def __init__(self, settings: Settings | None = None,
                 executor_factory: Callable[..., Executor] = WorkerExecutor):
        self._loop = asyncio.get_running_loop()
        self.settings = settings if settings is not None else load_settings()
        # The last run's autosave, moved aside before this run can autosave over it: the restore offer
        # (spec 9, 10) that session.get reports and session.restore takes.
        self._restorable = self._claim_autosave()
        self._executor_factory = executor_factory
        self._executor = self._new_executor()
        self._lock = asyncio.Lock()  # one session call (and so one tool) at a time
        self._subscribers: dict[asyncio.Queue, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()  # background work (auto replays, cleanups)
        self._turn: asyncio.Task | None = None
        self._turn_cfg: TurnConfig | None = None
        self._switching = 0  # session.new / session.open calls under way: no turn may start meanwhile
        self._provider: ScriptedProvider | None = None
        self._dirty = False  # the session changed since the last autosave
        self._closed = False
        # Two gates: the in-app turn's (Stop cancels it) and the CLI agents' (only a closed UI, a new or
        # opened session, or close() cancels it). Both check an edit's image ids against the open session.
        self.gate = ApprovalGate(self._emit, resolve=self._resolve_ref)
        self._cli_gate = ApprovalGate(self._emit, resolve=self._resolve_ref)
        self.path: Path | None = None  # the project file the session was opened from or saved to
        self.session = self._new_session("Untitled")
        self._dirty = False  # nothing autosaves until the session changes: an untouched core leaves none
        self._prev_progress = assets.PROGRESS
        assets.PROGRESS = self._on_progress
        self.dispatcher = Dispatcher()
        self._register()

    # --- plumbing -------------------------------------------------------------------------------

    def _new_executor(self) -> Executor:
        return self._executor_factory(timeout_s=self.settings.tool_timeout_s,
                                      max_rss_mb=self.settings.tool_memory_mb)

    def _output_dir(self) -> Path:
        chosen = self.settings.output_dir
        return Path(chosen).expanduser() if chosen else files.default_output_dir()

    def _session_kw(self) -> dict:
        return {"executor": self._executor, "emit": self._emit, "output_dir": self._output_dir(),
                "on_change": self._changed}

    def _new_session(self, name: str) -> Session:
        session = Session.new(name, **self._session_kw())
        session.data.approval_mode = self.settings.approval_mode
        return session

    def _changed(self) -> None:  # Session.on_change: called from whichever thread changed it
        self._dirty = True

    def _resolve_ref(self, ref: str) -> str:  # the gates' check of an edit's image ids (thread-safe, no disk)
        return self.session.artifacts.resolve(ref)

    def _log(self, level: str, message: str) -> None:
        self._emit("core.log", {"level": level, "message": message})

    @staticmethod
    def _claim_autosave() -> Path | None:
        """Keep the last run's autosave for the restore offer. claim_autosave never raises (a file it can't
        move stays for the next launch); should it ever, that only costs the offer: it is logged (no client
        is connected yet) and the core starts anyway."""
        try:
            return project.claim_autosave()
        except (EngineError, OSError) as e:
            log.warning("can't keep the last autosave to offer restoring it: %s", getattr(e, "message", e))
            return None

    def _autosave(self) -> None:
        """Runs in a worker thread under the lock. A failed autosave is reported, never raised."""
        if not self._dirty:
            return
        self._dirty = False
        try:
            project.autosave(self.session)
        except (EngineError, OSError) as e:
            self._log("warning", f"autosave failed: {getattr(e, 'message', e)}")

    async def _blocking(self, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
        """Run a session call in a thread, one at a time, then autosave if anything changed. This is
        the `blocking` run_turn gets. A thread can't be interrupted, so if the caller is cancelled the
        lock is held until the thread ends, and only then does the cancellation go on: the lock is never
        released while a thread is inside the session. (run_turn's Stop stops its step's tool through
        that step's own cancel event, even while the call still waits here for the lock; close() calls
        the executor's cancel() for any other call.)"""
        def work() -> Any:
            try:
                return fn(*args, **kw)
            finally:
                self._autosave()

        async with self._lock:
            fut = asyncio.ensure_future(asyncio.to_thread(work))
            try:
                return await asyncio.shield(fut)
            except asyncio.CancelledError:
                while not fut.done():
                    try:
                        await asyncio.wait({fut})
                    except asyncio.CancelledError:
                        pass
                if not fut.cancelled():
                    fut.exception()  # mark it retrieved: the caller is gone, so is its result
                raise

    def _emit(self, method: str, params: dict) -> None:
        """Queue an event for every subscriber. Callable from any thread (session calls run in threads)."""
        msg = rpc.notification(method, params)
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        if here is self._loop:
            self._deliver(msg)
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, msg)
        except RuntimeError:  # the loop is closed: nobody is listening any more
            pass

    def _deliver(self, msg: str) -> None:
        for queue in self._subscribers:
            queue.put_nowait(msg)

    async def _pump(self, queue: asyncio.Queue, send: Send) -> None:
        """Send one subscriber its events in order; a failed send drops the subscriber."""
        while True:
            msg = await queue.get()
            try:
                await send(msg)
            except Exception:
                log.debug("dropping a subscriber whose send failed", exc_info=True)
                self._subscribers.pop(queue, None)
                return

    def subscribe(self, send: Send) -> Callable[[], None]:
        """Receive every event (a JSON-RPC notification string) through `send`, in order. Returns the
        function that unsubscribes."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        pump = self._loop.create_task(self._pump(queue, send))
        self._subscribers[queue] = pump

        def unsubscribe() -> None:
            if self._subscribers.pop(queue, None) is not None:
                pump.cancel()

        return unsubscribe

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        task = self._loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _on_progress(self, name: str, done: int, total: int | None) -> None:  # assets.PROGRESS
        self._emit("asset.progress", {"name": name, "done": done, "total": total})

    def _snapshot(self) -> dict:
        """The session as saved (SessionData by alias) plus what the app knows about it."""
        return {**self.session.data.model_dump(mode="json", by_alias=True),
                "path": str(self.path) if self.path else None,
                "turn_running": self._turn is not None,
                "pending_approvals": self.gate.pending() + self._cli_gate.pending(),
                "restorable": str(self._restorable) if self._restorable else None}

    def _check_idle(self) -> None:
        if self._turn is not None:
            raise EngineError("the agent is still working", hint="press Stop, or wait for the turn to finish")

    def _cancel_approvals(self, note: str) -> None:
        """Reject every step waiting for approval, the turn's and the CLI agents'."""
        self.gate.cancel_all(note)
        self._cli_gate.cancel_all(note)

    def _get_provider(self) -> ScriptedProvider:
        if self._provider is None:
            path = self.settings.fake_provider_script or os.environ.get("BADSHOP_FAKE_PROVIDER")
            if not path:
                raise EngineError("no model provider is set up yet", hint=NO_PROVIDER_HINT)
            self._provider = ScriptedProvider.from_file(Path(path))  # a bad script is its own EngineError
        return self._provider

    # --- the agent turn -------------------------------------------------------------------------

    async def _turn_main(self, session: Session, provider: ScriptedProvider, text: str,
                         attachments: list[str], cfg: TurnConfig) -> None:
        finished = False  # run_turn announced the end itself

        def emit(method: str, params: dict) -> None:
            nonlocal finished
            finished = finished or method == "turn.finished"
            self._emit(method, params)

        try:
            await run_turn(session, provider, self.gate, text, attachments, cfg, emit,
                           blocking=self._blocking)
        except asyncio.CancelledError:  # stopped
            if not finished:
                self._emit("turn.finished", {"reason": "stopped"})
        except Exception as e:  # the turn broke: say so, and keep the core serving
            log.exception("the agent turn failed")
            self._log("error", f"the agent turn failed ({type(e).__name__}: {e})")
            if not finished:
                self._emit("turn.finished", {"reason": "error", "error": f"{type(e).__name__}: {e}"})
        finally:
            self._turn = self._turn_cfg = None
        await self._blocking(self._changed)  # one autosave of the session as the turn left it

    async def _stop_turn(self, note: str) -> bool:
        """Cancel the running turn and wait for it to end. run_turn rejects the steps it left waiting
        (Task 11), and `_reject_waiting` makes sure: a stopped turn never leaves a step "proposed". CLI
        agents' calls are not the turn's and keep waiting. False if no turn was running."""
        task, session = self._turn, self.session
        if task is None:
            return False
        task.cancel()
        await asyncio.wait({task})
        if self._turn is task:  # cancelled before it ever ran: its own cleanup never happened
            self._turn = self._turn_cfg = None
            self._emit("turn.finished", {"reason": "stopped"})
        await self._blocking(self._reject_waiting, session, note)
        return True

    @staticmethod
    def _reject_waiting(session: Session, note: str) -> None:
        """The safety net behind run_turn's own wind-up: an agent step still proposed is rejected. Under
        the lock, so two stops at once (a closed client, then close()) reject each step once."""
        for step in list(session.data.steps):
            if step.status == "proposed" and step.actor.startswith("agent:"):
                session.reject(step.id, note)

    def on_client_gone(self) -> None:
        """The last user client disconnected: stop the agent's turn and reject every pending approval
        (a CLI agent's too), so nothing waits for a user who isn't there. The core keeps serving, and
        the next client sees the session as it was left."""
        self._cancel_approvals("the user closed the app")
        if self._turn is not None:
            self._spawn(self._stop_turn("the user closed the app"))

    async def close(self) -> None:
        """Stop the turn and background work, autosave, close the executor, drop the subscribers."""
        if self._closed:
            return
        self._closed = True
        self._cancel_approvals("badshop is closing")
        await self._stop_turn("badshop is closing")
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        self._executor.cancel()  # kill a tool a replay is running; nothing runs on this executor again
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._blocking(lambda: None)  # a last autosave, if anything changed
        await asyncio.to_thread(self._executor.close)
        pumps = list(self._subscribers.values())
        self._subscribers.clear()
        for pump in pumps:
            pump.cancel()
        await asyncio.gather(*pumps, return_exceptions=True)
        if assets.PROGRESS == self._on_progress:
            assets.PROGRESS = self._prev_progress

    # --- methods: session -----------------------------------------------------------------------

    def _register(self) -> None:
        for name, handler, actors in (
            ("session.new", self._session_new, "user"),
            ("session.get", self._session_get, "user"),
            ("session.open", self._session_open, "user"),
            ("session.restore", self._session_restore, "user"),
            ("session.save", self._session_save, "user"),
            ("session.save_as", self._session_save_as, "user"),
            ("session.export_recipe", self._session_export_recipe, "user"),
            ("session.set_approval_mode", self._session_set_approval_mode, "user"),
            ("chat.send", self._chat_send, "user"),
            ("chat.stop", self._chat_stop, "user"),
            ("tools.list", self._tools_list, "any"),
            ("tools.run", self._tools_run, "any"),
            ("steps.edit", self._steps_edit, "user"),
            ("steps.replay_from", self._steps_replay_from, "user"),
            ("steps.delete", self._steps_delete, "user"),
            ("approval.respond", self._approval_respond, "user"),
            ("artifacts.get", self._artifacts_get, "any"),
            ("artifacts.import", self._artifacts_import, "user"),
            ("export", self._export, "user"),
            ("settings.get", self._settings_get, "user"),
            ("settings.set", self._settings_set, "user"),
            ("assets.status", self._assets_status, "user"),
            ("assets.download", self._assets_download, "user"),
        ):
            self.dispatcher.method(name, actors=actors)(handler)

    async def _switch(self, replace: Callable[[], None], note: str) -> dict:
        """session.new, session.open and session.restore: `replace` swaps the session in, under the lock.
        From the idle check until the swap is done no turn can start (chat.send refuses while `_switching`),
        so a turn never runs on a session that is being replaced; `replace` checks again under the lock. CLI
        calls still waiting for approval belong to the old session: they are rejected once it is gone, even
        when the caller of this method was cancelled (a swap whose thread has started always finishes; one
        cancelled while it waits for the lock never starts, and then nothing changes)."""
        self._check_idle()
        before = self.session
        self._switching += 1
        try:
            await self._blocking(replace)
        finally:
            self._switching -= 1
            if self.session is not before:
                self._cancel_approvals(note)
        return self._snapshot()

    async def _session_new(self, actor: str, name: SessionName = "Untitled") -> dict:
        def replace() -> None:
            self._check_idle()
            self.session, self.path = self._new_session(name), None
            self._dirty = True

        return await self._switch(replace, "the user started a new session")

    async def _session_get(self, actor: str) -> dict:
        return self._snapshot()

    async def _session_open(self, actor: str, path: str) -> dict:
        p = _user_path(path)

        def load() -> None:
            self._check_idle()
            session = project.open_project(p, **self._session_kw())  # any failure: the session is untouched
            # a file in the autosave folder is badshop's, not the user's project: Save must not write there
            autosaved = p.resolve().parent == project.autosave_path().parent.resolve()
            self.session, self.path = session, None if autosaved else p
            self._dirty = True

        return await self._switch(load, "the user opened another session")

    async def _session_restore(self, actor: str) -> dict:
        """Open the last run's autosave (the offer the snapshot's `restorable` names) as an unsaved
        session. Taking the offer uses it up; a failed restore changes nothing."""
        def load() -> None:
            self._check_idle()
            if self._restorable is None:
                raise EngineError("there is no autosaved session to restore",
                                  hint="the last run left no autosaved session, or it was restored already")
            session = project.open_project(self._restorable, **self._session_kw())
            self.session, self.path, self._restorable = session, None, None
            self._dirty = True  # autosaved at once: from now on this run's autosave holds it

        return await self._switch(load, "the user restored the autosaved session")

    async def _session_save(self, actor: str) -> dict:
        def save() -> Path:
            if self.path is None:
                raise EngineError("this session has no project file yet", hint="use Save As to pick one")
            return project.save(self.session, self.path)

        return {"path": str(await self._blocking(save))}

    async def _session_save_as(self, actor: str, path: str) -> dict:
        p = _user_path(path)

        def save() -> Path:
            self.path = project.save(self.session, p)
            return self.path

        return {"path": str(await self._blocking(save))}

    async def _session_export_recipe(self, actor: str, path: str) -> dict:
        p = _user_path(path)
        await self._blocking(lambda: _write_json(p, project.export_recipe(self.session)))
        return {"path": str(p)}

    async def _session_set_approval_mode(self, actor: str, mode: ApprovalMode) -> dict:
        def apply() -> None:
            self.session.data.approval_mode = mode
            self._dirty = True

        await self._blocking(apply)
        if self._turn_cfg is not None:  # the running turn follows the switch from its next tool call
            self._turn_cfg.approval_mode = mode
        return self._snapshot()

    # --- methods: chat --------------------------------------------------------------------------

    async def _chat_send(self, actor: str, text: str, attachments: list[str] | None = None) -> dict:
        self._check_idle()
        if self._switching:
            raise EngineError("the session is being replaced", hint="send the message again once it has opened")
        provider = self._get_provider()
        session = self.session
        ids = [session.artifacts.resolve(a) for a in attachments or []]  # a bad ref fails now, not mid-turn
        cfg = TurnConfig(approval_mode=session.data.approval_mode, step_budget=self.settings.step_budget)
        self._turn_cfg = cfg
        self._turn = self._spawn(self._turn_main(session, provider, text, ids, cfg))
        return {"started": True}

    async def _chat_stop(self, actor: str) -> dict:
        return {"stopped": await self._stop_turn("stopped by the user")}

    # --- methods: tools and steps ---------------------------------------------------------------

    async def _tools_list(self, actor: str) -> list[dict]:
        trusted = runner.is_trusted(actor)
        return [_tool_entry(spec, trusted) for spec in REGISTRY.values()]

    async def _tools_run(self, actor: str, tool: str, params: dict | None = None) -> dict:
        """The user's tools run at once. Any other actor's call is proposed, then waits for the approval
        the session's mode asks for (spec 7), exactly like the in-app agent's calls."""
        raw = params or {}
        if runner.is_trusted(actor):
            step = await self._blocking(lambda: self.session.run_tool(tool, raw, actor))
            return step.model_dump(mode="json")
        return await self._cli_call(actor, tool, raw)

    async def _cli_call(self, actor: str, tool: str, raw: dict) -> dict:
        """A CLI agent's call: proposed as that actor (so the session applies the untrusted rules), then it
        waits in the CLI gate, then it runs. However it ends, its step never stays waiting: a rejection or
        an edit the session refuses rejects it, and so does a caller that stops waiting (Task 13 cancels a
        closed connection's requests). chat.stop never touches it: Stop is about the in-app turn."""
        got: dict[str, Any] = {}

        def propose() -> Step:
            got["session"] = self.session  # read under the lock: the session the step really went into
            got["step"] = self.session.propose(tool, raw, actor)
            return got["step"]

        try:
            step = await self._blocking(propose)
            session, edited = got["session"], None
            if approval.needs_approval(registry.get(tool), session.data.approval_mode):
                decision = await self._cli_gate.request(step)
                if decision.decision == "reject":
                    step = await self._blocking(self._settle, session, step.id, decision.note)
                    return step.model_dump(mode="json")
                edited = decision.params if decision.decision == "edit" else None
            step = await self._blocking(self._run_or_reject, session, step.id, edited)
            return step.model_dump(mode="json")
        except asyncio.CancelledError:
            if "step" in got:  # proposed, and maybe still waiting: settle it before letting go
                await self._blocking(self._settle, got["session"], got["step"].id, "the agent stopped waiting")
            raise

    @staticmethod
    def _settle(session: Session, step_id: str, note: str | None) -> Step:
        """Reject a step that is still waiting to run; one that ran or was rejected already stays as it is."""
        step = session.step(step_id)
        return session.reject(step_id, note) if step.status in RUNNABLE else step

    @staticmethod
    def _run_or_reject(session: Session, step_id: str, params: dict | None) -> Step:
        """Run an approved (or user-edited) CLI step, with the fallback in the same locked call. The gate
        already checks an edit (valid as the user's, image ids in the session); should `Session.run` still
        refuse one, it does so before it changes the step, which would leave the step `proposed` with
        nothing waiting for it. It is rejected instead, as Task 11's `_execute` does for the in-app turn."""
        try:
            return session.run(step_id, params)
        except EngineError as e:
            if params is None:  # a proposed step runs on its own params: nothing to fall back to
                raise
            return session.reject(step_id, f"the edited parameters were refused: {e.message}")

    async def _steps_edit(self, actor: str, step_id: str, params: dict) -> dict:
        def edit() -> tuple[Session, list[Step]]:
            return self.session, self.session.edit(step_id, params)

        session, stale = await self._blocking(edit)
        if self.settings.auto_replay and stale:
            self._spawn(self._auto_replay(session, step_id))
        return {"stale": [s.id for s in stale]}

    async def _auto_replay(self, session: Session, step_id: str) -> None:
        try:
            await self._blocking(lambda: session.replay_from(step_id) if session is self.session else [])
        except Exception as e:  # nobody awaits this task: report instead of raising
            log.exception("auto replay failed")
            self._log("warning", f"replay failed: {getattr(e, 'message', e)}")

    async def _steps_replay_from(self, actor: str, step_id: str) -> list[dict]:
        steps = await self._blocking(lambda: self.session.replay_from(step_id))
        return [s.model_dump(mode="json") for s in steps]

    async def _steps_delete(self, actor: str, step_id: str) -> dict:
        await self._blocking(lambda: self.session.delete_last(step_id))
        return {"deleted": step_id}

    async def _approval_respond(self, actor: str, step_id: str, decision: Verdict, params: dict | None = None,
                                note: str | None = None) -> dict:
        # The gate checks an edit (valid as the user's, image ids in the session): a bad one is an
        # EngineError and the step waits on. A step in neither gate is the turn gate's clean EngineError.
        gate = self._cli_gate if step_id in self._cli_gate.pending() else self.gate
        gate.respond(step_id, decision, params, note)
        return {"ok": True}

    # --- methods: artifacts and files -----------------------------------------------------------

    async def _artifacts_get(self, actor: str, id: str, max_px: MaxPx | None = None) -> dict:
        # Artifacts are immutable, so reading one needs no lock: the viewer stays live while a tool runs.
        return await asyncio.to_thread(_artifact_payload, self.session, id, max_px)

    async def _artifacts_import(self, actor: str, path: str | None = None, data: str | None = None,
                                name: str | None = None) -> dict:
        if (path is None) == (data is None):
            raise RpcError(INVALID_PARAMS, "give either path or data",
                           {"hint": "path: a file the user picked; data: the image bytes in base64"})
        if path is not None:
            p = _user_path(path)
            blob = await asyncio.to_thread(_read_import, p)
            label = name or p.name
        else:
            try:
                blob = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise RpcError(INVALID_PARAMS, "data is not base64") from None
            label = name or ""

        def do() -> tuple:  # the store turns a file name into a label ("pasted" when there is none)
            working = self.session.import_image(blob, label)
            return working, self.session.artifacts.meta.get(working.original_id or "", working)

        working, original = await self._blocking(do)
        return {"working": working.model_dump(mode="json"), "original": original.model_dump(mode="json")}

    async def _export(self, actor: str, artifact_id: str, name: str | None = None) -> dict:
        path = await self._blocking(lambda: self.session.export(artifact_id, name))
        return {"path": str(path)}

    # --- methods: settings and assets -----------------------------------------------------------

    async def _settings_get(self, actor: str) -> dict:
        return self.settings.model_dump(mode="json")

    async def _settings_set(self, actor: str, values: dict) -> dict:
        try:
            new = Settings.model_validate({**self.settings.model_dump(), **values})
        except ValidationError as e:
            raise RpcError(INVALID_PARAMS, "invalid settings", {"hint": runner.explain(e)}) from None
        await self._blocking(self._apply_settings, new)
        return new.model_dump(mode="json")

    def _apply_settings(self, new: Settings) -> None:
        """Runs in a thread under the lock, so no tool is running while the executor is swapped."""
        save_settings(new)
        old, self.settings = self.settings, new
        if (new.tool_timeout_s, new.tool_memory_mb) != (old.tool_timeout_s, old.tool_memory_mb):
            retired, self._executor = self._executor, self._new_executor()
            self.session.executor = self._executor
            retired.close()
        self.session.output_dir = self._output_dir()
        if new.fake_provider_script != old.fake_provider_script:
            self._provider = None

    async def _assets_status(self, actor: str) -> list[dict]:
        return await asyncio.to_thread(manifest.status)

    async def _assets_download(self, actor: str, name: str) -> dict:
        # Not under the lock: a 170 MB model download must not hold up tools. Progress arrives as
        # asset.progress events through assets.PROGRESS.
        return {"path": str(await asyncio.to_thread(manifest.download, name))}
```

- [ ] **Step 7: Run the tests**

Run: `cd core && uv run pytest tests/test_server_app.py -v`
Expected: `22 passed` in about 3 seconds, offline (every tool they run needs no download).

Then run the whole suite: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1295 passed, 1 deselected` in about a minute and a half (Task 11's 1273 plus these 22; the deselected one is the `network` test), and ruff prints `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add core/pyproject.toml core/uv.lock core/src/badshop/server/__init__.py core/src/badshop/server/settings.py core/src/badshop/server/rpc.py core/src/badshop/server/app.py core/tests/test_server_app.py
git commit -m "feat(server): settings, JSON-RPC dispatcher, and CoreApp methods and events

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: WebSocket transport, handshake, `badshop-core` entry point, end-to-end test, docs

**Files:**
- Create: `core/src/badshop/server/ws.py`, `core/src/badshop/server/main.py`, `core/src/badshop/server/__main__.py`
- Modify: `core/src/badshop/server/app.py` (`steps.replay_from` takes `use_cache`), `core/pyproject.toml` (the `badshop-core` script; Task 12 added the dependencies), `README.md`, `docs/superpowers/plans/2026-09-26-roadmap.md`, `docs/superpowers/plans/2026-09-27-plan-1-carry-forward.md`
- Test: `core/tests/test_server_ws.py`

**Interfaces:**
- Consumes:
  - Task 12: `server.app.CoreApp(settings: Settings | None = None, executor_factory=WorkerExecutor)` with
    `dispatcher.handle(raw: str, actor: str) -> str | None` (async), `subscribe(send: Callable[[str], Awaitable[None]]) -> Callable[[], None]`,
    `on_client_gone() -> None` (plain function, called without `await`), `async close()` and the attribute `session`;
    `server.settings.load_settings() -> Settings`; `server.rpc.INTERNAL_ERROR`. The tests rely on these Task 12
    behaviours: the methods `session.get|open|save_as|restore`, `artifacts.import|get`, `chat.send`, `approval.respond`,
    `tools.run`, `steps.replay_from` (`-> [steps]`, the steps it ran); a snapshot is `SessionData.model_dump(mode="json",
    by_alias=True)` plus `path`, `turn_running`, `pending_approvals` and `restorable`; `CoreApp.__init__` calls Task 9's
    `project.claim_autosave()`, and `restorable` is the path it returned, as a string (`null` when there was no
    autosave); the user-only `session.restore {}` opens that file through `_switch` and answers the snapshot, with
    `path: null`; error codes `ENGINE_ERROR = -32000` and
    `FORBIDDEN = -32001`; the fake provider script read from `$BADSHOP_FAKE_PROVIDER`, settings from
    `$BADSHOP_CONFIG_DIR`; the default approval mode `"ask_changes"`; a subscriber receives events in the order they were
    emitted; a cancelled `_blocking` call holds the lock until its thread returns; a non-user `tools.run` whose caller is
    cancelled while it waits for approval rejects its step. This task changes one Task 12 handler, quoted in Step 5:
    `async def _steps_replay_from(self, actor: str, step_id: str) -> list[dict]`.
  - Task 11: the script format of `ScriptedProvider.from_file`; the events `turn.started`, `message.delta {"text"}`,
    `approval.needed {"step"}` and `turn.finished {"reason"}`; cancelling a turn rejects the step that was waiting for
    approval (`status == "rejected"` in the session).
  - Tasks 5 to 10: `session.artifacts.ArtifactStore().import_image(data, label) -> (working, original)`;
    `session.session.Session.new(name="Untitled", **kw)` with `executor=` and `output_dir=`, the attribute `executor`,
    `Session.import_image(data, label) -> ArtifactMeta`, `Session.run_tool(tool, raw, actor) -> Step`, and the events a
    step sends while it runs, `step.started` and then `step.finished` (both `{"step", "artifacts"}`);
    `Session.replay_from(step_id, *, use_cache: bool = True) -> list[Step]` (Task 8: with the cache on, a step whose
    `cache_key` matches a remembered successful run takes that run's results and announces no `step.started`; the
    remembered runs are the steps themselves, so they survive save and open); `session.execution.InProcessExecutor`;
    Task 9's `project.claim_autosave() -> Path | None` (`os.replace`s `<data dir>/autosave/session.badshop` to
    `<data dir>/autosave/previous.badshop` and returns that path; None when there is no autosave);
    `WorkerExecutor.cancel()` does nothing when no tool runs, and a cancel from before a call does not stop that call (Task 10);
    `WorkerExecutor.close()` has ended (and reaped) the worker process when it returns (Task 10), and `psutil` is a runtime
    dependency from Task 10 on (`Process.children`, `is_running`, `status`); Task 9's `project.open_project(path) -> Session`.
  - Plan 1: `badshop.__version__`; `tests/conftest.py`: `FIXTURES`, `cli_env(cwd) -> dict[str, str]` (the test
    caches, `BADSHOP_OUT`).
  - websockets 15/16: `websockets.asyncio.server.serve` (keyword arguments it doesn't take itself, `sock` among them, go
    to `loop.create_server`), `Server` (`close()`, which also closes the listening sockets, and `wait_closed()`: every
    connection gets 1001, then it waits for every connection handler to return), `ServerConnection`;
    `websockets.asyncio.client.connect`; `websockets.exceptions.ConnectionClosed` (`.rcvd.code`);
    `websockets.frames.CloseCode`. The standard library's `socket.create_server(address)` (a bound, listening socket).
- Produces:
  - `server/ws.py`: `HELLO_TIMEOUT_S = 10.0`, `MAX_MESSAGE = 64 * 2**20`,
    `ACTOR = re.compile(r"user|cli:(claude|codex|gemini)")` (always used with `fullmatch`),
    `async def serve(app: CoreApp, token: str, host: str = "127.0.0.1", port: int = 0, *, sock: socket.socket | None = None)
    -> websockets.asyncio.server.Server` (`sock`: a socket that is already listening, served instead of binding
    `host:port`; the brief's signature plus this keyword), `bound_port(server: Server) -> int`.
  - `server/main.py`: `build_parser() -> argparse.ArgumentParser` (`badshop-core [--version] serve [--port N]`),
    `main(argv: list[str] | None = None) -> int`.
  - `server/__main__.py`: `python -m badshop.server serve` runs `main()`.
  - `server/app.py`: `steps.replay_from {step_id, use_cache?}` (`use_cache` defaults to `true`; `false` runs every step
    again, spec §2 success criterion 4).
  - `pyproject.toml`: the console script `badshop-core = "badshop.server.main:main"`.
  - The wire contract later plans build on: the first stdout line is exactly `{"port": <int>, "token": "<token>"}`,
    and stdout carries nothing after it; the hello `{"type": "hello", "token", "actor"}` is answered with
    `{"type": "welcome", "actor", "version"}`, and a bad (including unparseable), late (10 s) or binary hello is closed
    with 1008; after the hello, a binary frame closes the connection with 1003; requests on one connection run
    concurrently (replies are matched by `id`), every request gets a reply, and replies and events leave each connection
    in the order they were produced; when a connection closes, the requests it still has open are cancelled (a call
    already inside a session thread finishes first) and the server waits for them; when the last `user` connection
    closes, `app.on_client_gone()` runs; from the handshake line on, SIGINT and SIGTERM exit 0 after closing every
    connection (1001), stopping a running tool and `app.close()` (a running turn stops as if the UI had closed, and the
    session is autosaved); when stdin is not a terminal, stdin reaching end of file stops the core the same way (exit 0,
    with `badshop-core: stdin closed ...` on stderr): the shell spawns the core with a stdin pipe it never writes to, so
    a core whose shell died without stopping it does not outlive it (spec §5.7; ruling R10); a port that can't be bound
    exits 1 with a message on stderr and no handshake line, before the app exists, so the last run's autosave stays
    where the next start offers it (spec §9).

Review Focus 1 (a client disconnects while a turn runs or a step waits for approval) is pinned twice: against the
real core by `test_closing_the_ui_during_an_approval_stops_the_turn_and_the_core_keeps_serving` (the turn stops,
the waiting step ends `rejected`, a new client sees the session, runs a tool and starts a new turn; then the shell
quits with that turn waiting, both clients get 1001 and the core exits 0; the next launch offers the autosave it left
(spec §9: `session.get` reports it as `restorable`, and `session.restore` brings the three steps back, that second
cutout rejected too), and at the transport by `test_only_the_last_user_leaving_counts_as_the_ui_gone` (including a
connection that drops without a close frame, as when the UI process is killed) and
`test_a_closed_connection_cancels_its_requests_and_the_server_waits_for_them`. Stopping a tool that the turn is
running at that moment is run_turn's job (Task 11), through the step's own cancel event that Task 10's
`WorkerExecutor.run` honours; their own tests cover it.

The end-to-end test cannot let the fake provider read tool results, so its script names every artifact id in
advance: `expected_ids` does the same work in-process first (the engine is deterministic), which also proves
that the worker process and the test process produce the same bytes. It then runs two core processes: the first
plays the turn and saves the project, the second (a fresh process, nothing in memory) opens it and replays from
the first step that changes pixels with `use_cache: false`. Task 8's cache lives in the steps, so it survives save
and open: with the cache on, that replay would reuse every step's saved result and run nothing. The test proves the
replay really ran: a `step.started` event for each of cutout, paste and text (a reused result sends none), and the
same artifact ids as the first process made (spec §2, success criterion 4).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_server_ws.py`:
```python
"""The WebSocket transport, the badshop-core entry point, and the whole core end to end (Task 13)."""

import asyncio
import base64
import hashlib
import itertools
import json
import signal
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from badshop import __version__
from badshop.server import main as core_main
from badshop.server import ws as transport
from badshop.server.ws import bound_port, serve
from badshop.session.artifacts import ArtifactStore
from badshop.session.execution import InProcessExecutor
from badshop.session.project import open_project
from badshop.session.session import Session
from conftest import FIXTURES, cli_env

TOKEN = "t0ken-for-tests"
WAIT_S = 120  # generous: the first tool call also starts the worker process


# ---- a JSON-RPC client over one connection -------------------------------------------------------------

class Client:
    """Sends one request at a time; keeps every notification it reads, in order, in `seen`."""

    def __init__(self, ws):
        self.ws = ws
        self.seen: list[dict] = []
        self._taken: set[int] = set()
        self._ids = itertools.count(1)

    async def _read(self) -> dict:
        return json.loads(await asyncio.wait_for(self.ws.recv(), WAIT_S))

    async def request(self, method: str, params: dict | None = None) -> dict:
        rid = next(self._ids)
        await self.ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                       "params": params or {}}))
        while True:
            msg = await self._read()
            if "id" not in msg:
                self.seen.append(msg)
            elif msg["id"] == rid:
                return msg

    async def call(self, method: str, params: dict | None = None):
        msg = await self.request(method, params)
        assert "error" not in msg, msg
        return msg["result"]

    async def fails(self, method: str, params: dict | None = None) -> dict:
        msg = await self.request(method, params)
        assert "error" in msg, msg
        return msg["error"]

    async def event(self, method: str) -> dict:
        """The params of the first notification called `method` not returned before, reading as needed."""
        while True:
            for i, e in enumerate(self.seen):
                if i not in self._taken and e["method"] == method:
                    self._taken.add(i)
                    return e["params"]
            msg = await self._read()
            assert "id" not in msg, f"a reply nobody asked for: {msg}"
            self.seen.append(msg)

    def methods(self) -> list[str]:
        return [e["method"] for e in self.seen]


@asynccontextmanager
async def client(port: int, token: str, actor: str = "user"):
    async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "token": token, "actor": actor}))
        welcome = json.loads(await asyncio.wait_for(ws.recv(), WAIT_S))
        assert welcome == {"type": "welcome", "actor": actor, "version": __version__}
        yield Client(ws)


async def closed_with(ws) -> int:
    """Read (and drop) whatever still arrives until the server closes the connection: its close code."""
    with pytest.raises(ConnectionClosed) as e:
        while True:
            await asyncio.wait_for(ws.recv(), WAIT_S)
    return e.value.rcvd.code


# ---- the transport, against a stand-in app -------------------------------------------------------------

class FakeApp:
    """What the transport uses of CoreApp: dispatcher.handle, subscribe and on_client_gone. Its methods:
    "who" answers with the caller's actor, "emit" sends an event first, "crash" raises (a bug), and "slow"
    waits for `release`; a cancelled "slow" takes a moment to clean up, as CoreApp waits for its thread."""

    def __init__(self):
        self.dispatcher = self
        self.subscribers = []
        self.gone = 0
        self.release = asyncio.Event()
        self.slow: list[int] = []  # ids of the "slow" calls that started
        self.cancelled: list[int] = []  # ids of the ones that were cancelled, once their cleanup is done

    async def handle(self, raw: str, actor: str) -> str | None:
        msg = json.loads(raw)
        if msg["method"] == "crash":
            raise RuntimeError("a bug in the app")
        if msg["method"] == "emit":
            for send in list(self.subscribers):
                await send(json.dumps({"jsonrpc": "2.0", "method": "ping", "params": msg["params"]}))
        if msg["method"] == "slow":
            self.slow.append(msg["id"])
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)
                self.cancelled.append(msg["id"])
                raise
        if "id" not in msg:
            return None
        return json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                           "result": {"method": msg["method"], "actor": actor}})

    def subscribe(self, send):
        self.subscribers.append(send)
        return lambda: self.subscribers.remove(send)

    def on_client_gone(self) -> None:
        self.gone += 1


@asynccontextmanager
async def fake_server():
    app = FakeApp()
    server = await serve(app, TOKEN)
    try:
        yield app, server
    finally:
        server.close()
        await server.wait_closed()


async def until(check) -> None:
    """Wait (at most 5 s) for the server side to catch up, e.g. to notice a closed connection."""
    for _ in range(500):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the server never got there")


def test_listens_on_loopback_and_answers_with_the_connection_actor():
    async def scenario():
        async with fake_server() as (app, server):
            host, port = server.sockets[0].getsockname()[:2]
            assert host == "127.0.0.1" and port == bound_port(server) > 0
            async with client(port, TOKEN, "user") as ui, client(port, TOKEN, "cli:codex") as cli:
                assert await ui.call("who") == {"method": "who", "actor": "user"}
                assert await cli.call("who") == {"method": "who", "actor": "cli:codex"}
                assert len(app.subscribers) == 2

    asyncio.run(scenario())


BAD_HELLOS = [json.dumps(h) for h in (
    {"type": "hello", "token": "wrong", "actor": "user"},
    {"type": "hello", "actor": "user"},
    {"type": "hello", "token": 12345, "actor": "user"},
    {"type": "hello", "token": "tökén", "actor": "user"},  # non-ASCII: compare_digest on str would raise
    {"type": "hello", "token": "\ud800", "actor": "user"},  # a lone surrogate can't even be encoded
    {"type": "hello", "token": TOKEN, "actor": "agent:fake"},  # agents run inside the core
    {"type": "hello", "token": TOKEN, "actor": "cli:cursor"},
    {"type": "hello", "token": TOKEN, "actor": "user\n"},  # `$` would match before a trailing newline
    {"type": "hello", "token": TOKEN},
    {"type": "hi", "token": TOKEN, "actor": "user"},
    ["hello", TOKEN, "user"],
)] + ["hello",  # not JSON
      "[" * 100_000]  # nested too deep: the JSON parser raises RecursionError, not ValueError


@pytest.mark.parametrize("hello", BAD_HELLOS, ids=range(len(BAD_HELLOS)))
def test_a_bad_hello_is_closed_with_1008(hello):
    async def scenario():
        async with fake_server() as (app, server):
            async with connect(f"ws://127.0.0.1:{bound_port(server)}") as ws:
                await ws.send(hello)
                assert await closed_with(ws) == 1008
            assert app.subscribers == [] and app.gone == 0  # never counted as a client

    asyncio.run(scenario())


def test_a_binary_first_message_or_no_hello_at_all_is_closed_with_1008(monkeypatch):
    monkeypatch.setattr(transport, "HELLO_TIMEOUT_S", 0.2)

    async def scenario():
        async with fake_server() as (app, server):
            url = f"ws://127.0.0.1:{bound_port(server)}"
            async with connect(url) as ws:
                await ws.send(json.dumps({"type": "hello", "token": TOKEN, "actor": "user"}).encode())
                assert await closed_with(ws) == 1008
            async with connect(url) as ws:  # says nothing
                assert await closed_with(ws) == 1008

    asyncio.run(scenario())


def test_binary_frames_after_the_hello_close_the_connection():
    async def scenario():
        async with fake_server() as (app, server):
            async with client(bound_port(server), TOKEN) as ui:
                await ui.ws.send(b'{"jsonrpc": "2.0", "id": 1, "method": "who"}')
                assert await closed_with(ui.ws) == 1003
            await until(lambda: app.gone == 1)

    asyncio.run(scenario())


def test_requests_run_concurrently_and_events_keep_their_order():
    async def scenario():
        async with fake_server() as (app, server):
            async with client(bound_port(server), TOKEN) as ui:
                for msg in ({"jsonrpc": "2.0", "id": 1, "method": "slow"},
                            {"jsonrpc": "2.0", "id": 2, "method": "emit", "params": {"n": 1}},
                            {"jsonrpc": "2.0", "method": "emit", "params": {"n": 2}}):
                    await ui.ws.send(json.dumps(msg))
                got = [json.loads(await asyncio.wait_for(ui.ws.recv(), WAIT_S)) for _ in range(3)]
                # the slow request holds up nothing; each event arrives before the reply that followed it
                assert got == [
                    {"jsonrpc": "2.0", "method": "ping", "params": {"n": 1}},
                    {"jsonrpc": "2.0", "id": 2, "result": {"method": "emit", "actor": "user"}},
                    {"jsonrpc": "2.0", "method": "ping", "params": {"n": 2}},
                ]
                app.release.set()
                reply = json.loads(await asyncio.wait_for(ui.ws.recv(), WAIT_S))
                assert reply == {"jsonrpc": "2.0", "id": 1, "result": {"method": "slow", "actor": "user"}}
            assert app.cancelled == []  # it had finished before the connection closed

    asyncio.run(scenario())


def test_a_request_the_app_fails_to_answer_still_gets_an_error_and_the_connection_goes_on(caplog):
    async def scenario():
        async with fake_server() as (app, server):
            async with client(bound_port(server), TOKEN) as ui:
                await ui.ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "crash"}))
                reply = json.loads(await asyncio.wait_for(ui.ws.recv(), WAIT_S))
                assert reply["id"] is None and reply["error"]["code"] == -32603
                assert await ui.call("who") == {"method": "who", "actor": "user"}

    asyncio.run(scenario())
    assert "a request crashed the dispatcher" in caplog.text


def test_a_closed_connection_cancels_its_requests_and_the_server_waits_for_them():
    async def scenario():
        app = FakeApp()
        server = await serve(app, TOKEN)
        try:
            port = bound_port(server)
            async with client(port, TOKEN) as ui:
                await ui.ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slow"}))
                await until(lambda: app.slow == [1])
            await until(lambda: app.cancelled == [1])  # the UI left: nobody is waiting for that answer
            async with client(port, TOKEN) as ui:
                await ui.ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "slow"}))
                await until(lambda: app.slow == [1, 2])
                server.close()  # what main does on SIGTERM
                assert await closed_with(ui.ws) == 1001  # going away
                await server.wait_closed()
                assert app.cancelled == [1, 2]  # wait_closed returned only after that request had ended
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_only_the_last_user_leaving_counts_as_the_ui_gone():
    async def scenario():
        async with fake_server() as (app, server):
            port = bound_port(server)
            async with client(port, TOKEN, "cli:claude"):
                async with client(port, TOKEN) as first:
                    async with client(port, TOKEN):
                        await until(lambda: len(app.subscribers) == 3)
                    await until(lambda: len(app.subscribers) == 2)
                    assert app.gone == 0  # another user client is still there
                    first.ws.transport.abort()  # the UI process dies: no close frame
                    await until(lambda: app.gone == 1)
                assert len(app.subscribers) == 1
            await until(lambda: app.subscribers == [])
            assert app.gone == 1  # a CLI agent leaving is not the UI closing

    asyncio.run(scenario())


def test_port_argument_is_checked(capsys):
    for bad in ("-1", "65536", "http"):
        with pytest.raises(SystemExit) as e:
            core_main.main(["serve", "--port", bad])
        assert e.value.code == 2
        assert "is not a port number" in capsys.readouterr().err


def test_a_busy_port_is_a_clean_error_and_changes_nothing(tmp_path):
    env = cli_env(tmp_path)
    env["BADSHOP_CONFIG_DIR"] = str(tmp_path / "config")
    env["BADSHOP_DATA_DIR"] = str(tmp_path / "data")
    last_run = tmp_path / "data" / "autosave" / "session.badshop"  # what the last run left
    last_run.parent.mkdir(parents=True)
    last_run.write_bytes(b"the last run's autosave")
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        p = subprocess.run([sys.executable, "-m", "badshop.server", "serve", "--port", str(port)],
                           cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
                           timeout=WAIT_S)
    assert p.returncode == 1 and p.stdout == ""  # no handshake line: the shell sees the exit
    assert f"can't listen on 127.0.0.1:{port}" in p.stderr and "Traceback" not in p.stderr
    # The start failed before the app existed, so the autosave was not set aside for a restore offer
    # this run will never make: the next start that does listen still offers it.
    assert [f.name for f in last_run.parent.iterdir()] == ["session.badshop"]
    assert last_run.read_bytes() == b"the last run's autosave"


# ---- the real core, as the desktop shell runs it -------------------------------------------------------

class Core:
    """A running `python -m badshop.server serve`: its port and token, and the two ways the desktop shell's
    going away reaches it."""

    def __init__(self, proc: asyncio.subprocess.Process, port: int, token: str):
        self.proc, self.port, self.token = proc, port, token
        self.stopped = False

    def stop(self) -> None:
        """SIGTERM, as the desktop shell sends when it quits (sent once, and not after hang_up)."""
        if not self.stopped:
            self.stopped = True
            self.proc.send_signal(signal.SIGTERM)

    def hang_up(self) -> None:
        """Close the core's stdin, as happens when the shell dies without stopping it (once, and not after
        stop)."""
        if not self.stopped:
            self.stopped = True
            self.proc.stdin.close()


@asynccontextmanager
async def core(root: Path, script: list | None = None, data: Path | None = None):
    """`python -m badshop.server serve` with the test caches, a private config folder, an optional
    fake-provider script and an optional private data folder (where the autosave goes; the default is the
    test cache's, which holds the fonts and models). Its stdin is a pipe the test never writes to, as the
    shell spawns it (spec §5.7): pytest's own stdin may be /dev/null (in CI, say), which would stop the
    core at once. Leaving the block stops the core with SIGTERM (unless the block stopped it or hung
    up) and checks a clean exit."""
    root.mkdir(parents=True, exist_ok=True)
    env = cli_env(root)
    env["BADSHOP_CONFIG_DIR"] = str(root / "config")
    if data is not None:
        env["BADSHOP_DATA_DIR"] = str(data)
    if script is not None:
        (root / "script.json").write_text(json.dumps(script), encoding="utf-8")
        env["BADSHOP_FAKE_PROVIDER"] = str(root / "script.json")
    log = root / "core.log"
    with open(log, "wb") as err:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "badshop.server", "serve", cwd=root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err)
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), WAIT_S)
            assert line, f"the core exited before its handshake:\n{log.read_text(encoding='utf-8')}"
            hello = json.loads(line)
            assert line == f'{{"port": {hello["port"]}, "token": "{hello["token"]}"}}\n'.encode()
            assert len(hello["token"]) >= 32
            running = Core(proc, hello["port"], hello["token"])
            yield running
            running.stop()
            assert await asyncio.wait_for(proc.wait(), WAIT_S) == 0, log.read_text(encoding="utf-8")
            assert await proc.stdout.read() == b""  # stdout carried the handshake and nothing else
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    assert "Traceback" not in log.read_text(encoding="utf-8")


def working_id(name: str) -> str:
    """The artifact id the core gives a fixture's working copy (imports are deterministic)."""
    return ArtifactStore().import_image((FIXTURES / f"{name}.png").read_bytes(), name)[0].id


def test_closing_the_ui_during_an_approval_stops_the_turn_and_the_core_keeps_serving(tmp_path):
    trump = working_id("trump")
    cut = {"name": "cutout", "arguments": {"image": trump, "box": [147, 159, 329, 330], "no_ai": True}}
    # Every reply asks for the same cutout, so the second turn asks again whether the core makes the
    # provider once or per turn.
    script = [{"text": "Cutting the face out.", "tool_calls": [cut]},
              {"text": "Once more.", "tool_calls": [cut]}]
    data = tmp_path / "data"  # private: the next launch finds the autosave this core leaves here

    async def scenario() -> None:
        async with core(tmp_path, script, data) as running:
            port, token = running.port, running.token
            async with client(port, token, "cli:claude") as watcher:
                async with client(port, token) as ui:
                    imported = await ui.call("artifacts.import", {"path": str(FIXTURES / "trump.png")})
                    assert imported["working"]["id"] == trump
                    sent = await ui.call("chat.send", {"text": "cut the face out", "attachments": [trump]})
                    assert sent == {"started": True}
                    first = (await ui.event("approval.needed"))["step"]
                    assert first["tool"] == "cutout" and first["status"] == "proposed"
                # the UI closed with the cutout still waiting: the turn stops
                assert await watcher.event("turn.finished") == {"reason": "stopped"}
                assert (await watcher.fails("session.get"))["code"] == -32001  # a user-only method
                async with client(port, token) as ui:  # the app comes back and sees the session
                    snap = await ui.call("session.get")
                    assert (snap["turn_running"], snap["pending_approvals"]) == (False, [])
                    assert snap["restorable"] is None  # the first launch: no earlier run to restore
                    step = snap["steps"][0]
                    assert (step["id"], step["tool"], step["status"]) == (first["id"], "cutout", "rejected")
                    gone = await ui.fails("approval.respond", {"step_id": step["id"], "decision": "approve"})
                    assert gone["code"] == -32000  # nothing waits for that approval any more
                    ran = await ui.call("tools.run", {"tool": "info", "params": {"image": trump}})
                    assert ran["status"] == "done" and ran["data"] == {"width": 474, "height": 600}
                    assert await ui.call("chat.send", {"text": "try again"}) == {"started": True}
                    second = (await ui.event("approval.needed"))["step"]
                    assert second["tool"] == "cutout"
                    # The shell quits with this cutout waiting: every client is told "going away".
                    running.stop()
                    assert await closed_with(ui.ws) == 1001
                assert await closed_with(watcher.ws) == 1001
        # Leaving `core` checked a clean exit (0), nothing more on stdout and no traceback. The next launch
        # offers what that core autosaved on the way out (spec §9), and it shows the second turn stopped
        # as if the UI had closed:
        async with core(tmp_path / "next", data=data) as relaunched:
            async with client(relaunched.port, relaunched.token) as ui:
                snap = await ui.call("session.get")
                assert snap["steps"] == []  # a new session, and the offer to restore the last one
                assert Path(snap["restorable"]) == data / "autosave" / "previous.badshop"
                restored = await ui.call("session.restore")
                assert restored["path"] is None  # the autosave is not the user's project file
                assert [(s["id"], s["status"]) for s in restored["steps"]] == [
                    (first["id"], "rejected"), (ran["id"], "done"), (second["id"], "rejected")]

    asyncio.run(scenario())


def running_ones(procs: list[psutil.Process]) -> list[psutil.Process]:
    """Those of `procs` that still run (one that has exited and only waits to be reaped has ended)."""
    alive = []
    for p in procs:
        try:
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                alive.append(p)
        except psutil.NoSuchProcess:
            pass
    return alive


def test_the_core_stops_cleanly_when_its_stdin_closes(tmp_path):
    """Spec §5.7, ruling R10: the shell spawns the core with a stdin pipe it never writes to. A shell that
    dies without stopping the core closes that pipe, and the core stops as it does on SIGTERM (clients get
    1001, the session is autosaved, the tool worker is closed, exit 0) instead of outliving it."""
    trump = working_id("trump")
    data = tmp_path / "data"  # private: the test reads back the autosave this core leaves

    async def scenario() -> str:
        async with core(tmp_path, data=data) as running:
            async with client(running.port, running.token) as ui:
                await ui.call("artifacts.import", {"path": str(FIXTURES / "trump.png")})
                ran = await ui.call("tools.run", {"tool": "info", "params": {"image": trump}})
                assert ran["status"] == "done" and ran["data"] == {"width": 474, "height": 600}
                started = psutil.Process(running.proc.pid).children(recursive=True)
                assert started  # the tool worker (and, on POSIX, multiprocessing's resource tracker)
                running.hang_up()  # the shell is gone: nothing holds the other end of the pipe any more
                assert await closed_with(ui.ws) == 1001  # the same clean stop as SIGTERM
            assert await asyncio.wait_for(running.proc.wait(), 10) == 0  # at once, not at some timeout
            await until(lambda: not running_ones(started))  # nothing the core started outlives it
        # Leaving `core` checked that nothing more came on stdout and that the log has no traceback.
        return ran["id"]

    step_id = asyncio.run(scenario())
    assert "badshop-core: stdin closed" in (tmp_path / "core.log").read_text(encoding="utf-8")
    autosaved = open_project(data / "autosave" / "session.badshop")
    assert [(s.id, s.tool, s.status) for s in autosaved.data.steps] == [(step_id, "info", "done")]
    assert trump in autosaved.data.artifacts


# The turn the fake provider plays: find (read-only, so it just runs), then cutout, paste and text, each
# waiting for approval (the default "ask_changes" mode). The user widens the cutout box before approving.
FIND = {"what": "faces"}
CUT = {"box": [147, 159, 329, 330], "oval": True}
CUT_EDITED = {"box": [140, 150, 336, 340], "oval": True}
PASTE = {"fit_box": [117, 123, 296, 310], "scale": 1.1}
CAPTION = {"text": "four score and seven memes ago", "bottom": True}


def expected_ids(out: Path) -> dict[str, str]:
    """The same work done in-process: the ids the core must produce (the engine is deterministic)."""
    s = Session.new(executor=InProcessExecutor(), output_dir=out)
    ids = {n: s.import_image((FIXTURES / f"{n}.png").read_bytes(), n).id for n in ("lincoln", "trump")}
    ids["cut"] = s.run_tool("cutout", {"image": ids["trump"], **CUT_EDITED}, "user").outputs[0]
    ids["pasted"] = s.run_tool("paste", {"base": ids["lincoln"], "piece": ids["cut"], **PASTE},
                               "user").outputs[0]
    ids["captioned"] = s.run_tool("text", {"image": ids["pasted"], **CAPTION}, "user").outputs[0]
    return ids


@pytest.mark.models  # find uses YuNet, and text the Impact lookalike font
def test_end_to_end_turn_save_reopen_and_replay(tmp_path):
    ids = expected_ids(tmp_path / "in-process")
    lincoln, trump = ids["lincoln"], ids["trump"]
    script = [
        {"text": "Finding the faces first.",
         "tool_calls": [{"name": "find", "arguments": {"image": trump, **FIND}}]},
        {"text": "", "tool_calls": [{"name": "cutout", "arguments": {"image": trump, **CUT}}]},
        {"text": "", "tool_calls": [{"name": "paste", "arguments": {
            "base": lincoln[:8], "piece": ids["cut"], **PASTE}}]},  # a short ref, as models write them
        {"text": "", "tool_calls": [{"name": "text", "arguments": {"image": ids["pasted"], **CAPTION}}]},
        {"text": "Done: bad, as requested."},
    ]
    project = tmp_path / "trumpcoln.badshop"

    async def first_run() -> dict:
        async with core(tmp_path / "first", script) as running:
            async with connect(f"ws://127.0.0.1:{running.port}") as ws:
                await ws.send(json.dumps({"type": "hello", "token": running.token[:-1], "actor": "user"}))
                assert await closed_with(ws) == 1008
            async with client(running.port, running.token) as ui:
                for name in ("lincoln", "trump"):
                    got = await ui.call("artifacts.import", {"path": str(FIXTURES / f"{name}.png")})
                    assert got["working"]["id"] == ids[name]
                sent = await ui.call("chat.send", {"text": "put trump's face on lincoln",
                                                   "attachments": [lincoln, trump]})
                assert sent == {"started": True}

                need = (await ui.event("approval.needed"))["step"]
                assert need["tool"] == "cutout" and need["params"]["box"] == CUT["box"]
                ran = [e["params"]["step"]["tool"] for e in ui.seen if e["method"] == "step.finished"]
                assert ran == ["find"]  # read-only: it did not wait
                await ui.call("approval.respond", {"step_id": need["id"], "decision": "edit",
                                                   "params": {"image": trump, **CUT_EDITED}})
                for tool in ("paste", "text"):
                    need = (await ui.event("approval.needed"))["step"]
                    assert need["tool"] == tool
                    await ui.call("approval.respond", {"step_id": need["id"], "decision": "approve"})
                assert await ui.event("turn.finished") == {"reason": "done"}
                assert ui.methods()[0] == "turn.started"
                said = "".join(e["params"]["text"] for e in ui.seen if e["method"] == "message.delta")
                assert "Done: bad, as requested." in said
                finished = [e["params"]["step"] for e in ui.seen if e["method"] == "step.finished"]
                assert [(s["tool"], s["status"]) for s in finished] == [
                    ("find", "done"), ("cutout", "done"), ("paste", "done"), ("text", "done")]

                snap = await ui.call("session.get")
                steps = snap["steps"]
                assert [(s["tool"], s["actor"], s["status"]) for s in steps] == [
                    (tool, "agent:fake", "done") for tool in ("find", "cutout", "paste", "text")]
                assert steps[1]["params"]["box"] == CUT_EDITED["box"]  # the user's edit is what ran
                assert steps[2]["params"]["base"] == lincoln  # stored params hold full ids
                assert [s["outputs"][0] for s in steps[1:]] == [ids["cut"], ids["pasted"], ids["captioned"]]
                assert snap["artifacts"][ids["captioned"]]["produced_by"] == steps[3]["id"]
                got = await ui.call("artifacts.get", {"id": ids["captioned"]})
                assert hashlib.sha256(base64.b64decode(got["data"])).hexdigest() == ids["captioned"]

                saved = await ui.call("session.save_as", {"path": str(project)})
                assert Path(saved["path"]) == project and project.is_file()
                return snap

    async def second_run(before: dict) -> None:
        async with core(tmp_path / "second") as running:  # a new process: nothing carried over
            async with client(running.port, running.token) as ui:
                assert (await ui.call("session.get"))["steps"] == []
                reopened = await ui.call("session.open", {"path": str(project)})
                for key in ("messages", "steps", "artifacts"):
                    assert reopened[key] == before[key], key
                redo = [s["id"] for s in before["steps"][1:]]  # cutout, paste, text: the steps that make pixels
                # use_cache False: the reopened steps' own results would otherwise be reused, and nothing
                # would run at all
                replayed = await ui.call("steps.replay_from", {"step_id": redo[0], "use_cache": False})
                assert [s["id"] for s in replayed] == redo
                # every one of them really ran again: a reused result announces no step.started (events
                # leave before the reply that follows them, so they are all in `seen` by now) ...
                started = [e["params"]["step"]["id"] for e in ui.seen if e["method"] == "step.started"]
                assert started == redo
                # ... in this process's own tool worker, and made the same pixels, byte for byte
                # (spec §2, success criterion 4)
                assert [(s["status"], s["outputs"]) for s in replayed] == [
                    ("done", s["outputs"]) for s in before["steps"][1:]]
                after = (await ui.call("session.get"))["steps"]
                assert [(s["status"], s["outputs"]) for s in after] == [
                    ("done", s["outputs"]) for s in before["steps"]]

    asyncio.run(second_run(asyncio.run(first_run())))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_server_ws.py -q`
Expected: a collection error, `ImportError: cannot import name 'main' from 'badshop.server'` (Task 12 made the
`badshop.server` package; `main.py` and `ws.py` do not exist yet).

- [ ] **Step 3: Implement the transport**

`core/src/badshop/server/ws.py`:
```python
"""The WebSocket transport (spec §5.6): a token handshake, then JSON-RPC 2.0 in text frames both ways."""

import asyncio
import contextlib
import hmac
import json
import logging
import re
import socket
from dataclasses import dataclass

from websockets.asyncio.server import Server, ServerConnection
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed
from websockets.frames import CloseCode

from badshop import __version__
from badshop.server.app import CoreApp
from badshop.server.rpc import INTERNAL_ERROR

HELLO_TIMEOUT_S = 10.0
MAX_MESSAGE = 64 * 2**20  # a big photo sent to artifacts.import as base64
ACTOR = re.compile(r"user|cli:(claude|codex|gemini)")  # agent:* actors live in the core, never on a socket

log = logging.getLogger("badshop.server")


@dataclass
class _Clients:
    users: int = 0  # open connections whose actor is "user"


async def _hello(ws: ServerConnection, token: str) -> str | None:
    """The actor the first message names, or None once the connection is closed with 1008."""
    try:
        raw = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S)
    except TimeoutError:
        await ws.close(CloseCode.POLICY_VIOLATION, "no hello")
        return None
    try:
        msg = json.loads(raw) if isinstance(raw, str) else None
    except (ValueError, RecursionError):  # not JSON, or nested too deep for the parser
        msg = None
    given = msg.get("token") if isinstance(msg, dict) else None
    actor = msg.get("actor") if isinstance(msg, dict) else None
    if not isinstance(msg, dict) or msg.get("type") != "hello":
        reason = "the first message must be a hello"
    elif not isinstance(given, str) or not hmac.compare_digest(
            given.encode("utf-8", "surrogatepass"), token.encode("utf-8")):
        reason = "bad token"
    elif not isinstance(actor, str) or not ACTOR.fullmatch(actor):
        reason = "unknown actor"
    else:
        return actor
    await ws.close(CloseCode.POLICY_VIOLATION, reason)
    return None


async def _write(ws: ServerConnection, outbox: asyncio.Queue) -> None:
    """The connection's only writer: replies and events leave in the order they were queued."""
    with contextlib.suppress(ConnectionClosed):
        while True:
            await ws.send(await outbox.get())


async def _answer(app: CoreApp, raw: str, actor: str, outbox: asyncio.Queue) -> None:
    try:
        reply = await app.dispatcher.handle(raw, actor)
    except Exception:  # the dispatcher answers every frame itself, so this is a bug; still answer
        log.exception("a request crashed the dispatcher")
        reply = json.dumps({"jsonrpc": "2.0", "id": None, "error": {
            "code": INTERNAL_ERROR, "message": "internal error",
            "data": {"hint": "this is a bug in badshop; the session is unaffected"}}})
    if reply is not None:
        outbox.put_nowait(reply)


async def _connection(app: CoreApp, token: str, clients: _Clients, ws: ServerConnection) -> None:
    try:
        actor = await _hello(ws, token)
        if actor is None:
            return
        await ws.send(json.dumps({"type": "welcome", "actor": actor, "version": __version__}))
    except ConnectionClosed:  # gone before the handshake finished
        return
    outbox: asyncio.Queue[str] = asyncio.Queue()

    async def send(message: str) -> None:
        outbox.put_nowait(message)

    writer = asyncio.create_task(_write(ws, outbox))
    requests: set[asyncio.Task] = set()  # in flight; the strong refs keep them alive
    unsubscribe = app.subscribe(send)
    if actor == "user":
        clients.users += 1
    try:
        async for raw in ws:
            if not isinstance(raw, str):
                await ws.close(CloseCode.UNSUPPORTED_DATA, "JSON-RPC goes in text frames")
                break
            # Each request runs as its own task, so a long tools.run never holds up an approval.respond.
            task = asyncio.create_task(_answer(app, raw, actor, outbox))
            requests.add(task)
            task.add_done_callback(requests.discard)
    except ConnectionClosed:  # an error code, or no close frame at all: the UI process died
        pass
    finally:
        unsubscribe()
        writer.cancel()
        pending = list(requests)
        for task in pending:  # nobody is left to read the answers
            task.cancel()
        if actor == "user":
            clients.users -= 1
            if clients.users == 0:
                app.on_client_gone()  # the UI is gone: stop the turn, reject what waits for approval
        # Wait for them: a call already in a session thread finishes first, and the server's
        # wait_closed() (so main's app.close()) only returns once every request has ended.
        await asyncio.gather(writer, *pending, return_exceptions=True)


async def serve(app: CoreApp, token: str, host: str = "127.0.0.1", port: int = 0, *,
                sock: socket.socket | None = None) -> Server:
    """Listen for clients of `app` on host:port (port 0: a free one), or on `sock`, a socket that is
    already listening (main binds it before it makes the app). `close()` the returned server (it closes
    `sock` too), then `await wait_closed()`: every connection gets 1001, and it returns once every
    request has ended."""
    clients = _Clients()

    async def handler(ws: ServerConnection) -> None:
        await _connection(app, token, clients, ws)

    where = {"sock": sock} if sock is not None else {"host": host, "port": port}
    # compression=None: on loopback deflate only costs CPU, and most payloads are base64 images anyway
    return await ws_serve(handler, max_size=MAX_MESSAGE, compression=None, **where)


def bound_port(server: Server) -> int:
    return server.sockets[0].getsockname()[1]
```

Why each connection has one writer task and one task per request: `tools.run` can take seconds (up to the
worker's 120 s), and while it runs the same connection must still get `approval.respond` answered and events
delivered. Running each request as its own task keeps the connection responsive; queueing every reply and event
through one `outbox` keeps them in the order they were produced (a `step.finished` event before the `tools.run`
reply that follows it).

When a connection closes, nobody is left to read its answers, so its open requests are cancelled: one still
waiting for CoreApp's lock never runs, and a CLI agent's `tools.run` waiting for approval rejects its step (Task
12). A request whose session call is already running in a thread is not interrupted: CoreApp's `_blocking` holds
the lock until the thread returns, so a user's own `tools.run` still finishes when the webview reloads, and the
reconnected UI sees the step in `session.get`. The handler waits for all of them before it returns. That wait is
what makes shutdown safe: `server.wait_closed()` returns only once every handler has returned, so when main calls
`app.close()`, no request is left inside the app to race the executor's `close()` or the last autosave.

Task 12's dispatcher turns every failure into a JSON-RPC error itself. The `except Exception` in `_answer` is only
a backstop for a bug there: the request still gets an answer (`-32603`, id `null`), the traceback goes to the log,
and the connection stays up.

- [ ] **Step 4: Implement the entry point**

`core/src/badshop/server/main.py`:
```python
"""`badshop-core`: the headless core that the desktop shell (and, from Plan 5, MCP proxies) talk to."""

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import signal
import socket
import sys
import threading

from badshop import __version__
from badshop.server.app import CoreApp
from badshop.server.settings import load_settings
from badshop.server.ws import bound_port, serve


def _port(text: str) -> int:
    n = int(text) if text.isdigit() else -1
    if not 0 <= n <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port number (0-65535; 0 picks a free one)")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="badshop-core", description="The badshop core: sessions, tools and the "
                                "agent, served to the app over a local WebSocket.")
    p.add_argument("--version", action="version", version=f"badshop-core {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="serve the local API; the first stdout line is the port and token")
    s.add_argument("--port", type=_port, default=0, help="port on 127.0.0.1 (default: a free one)")
    return p


def _stdout_to_stderr() -> None:
    """After the handshake stdout carries nothing more: point it at stderr (the log), so a stray print from a
    library or the tool worker can neither break the protocol nor block on a pipe nobody reads."""
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())


def _install_stop() -> asyncio.Event:
    """From now on SIGINT (Ctrl-C) and SIGTERM (the shell quitting) set the returned event instead of
    killing the process."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops have no signal handlers
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    return stop


def _stop_at_stdin_eof(stop: asyncio.Event) -> None:
    """When stdin is not a terminal, set `stop` once stdin reaches end of file (spec §5.7). The desktop
    shell spawns the core with a stdin pipe it never writes to: if the shell dies without stopping the core,
    its end of the pipe closes, and the core stops as on SIGTERM instead of running on with nobody to serve.
    Anything written to stdin is read and dropped. A terminal is left alone (Ctrl-C stops the core there)."""
    if sys.stdin is None:  # started without a stdin at all (fd 0 closed): nothing to watch
        return
    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError):
        return
    if os.isatty(fd):
        return
    loop = asyncio.get_running_loop()

    def at_eof() -> None:
        if stop.is_set():  # a signal came first
            return
        stop.set()  # before the message: a dead shell may have taken the stderr pipe with it
        with contextlib.suppress(OSError):
            print("badshop-core: stdin closed (whoever started the core is gone); stopping",
                  file=sys.stderr, flush=True)

    def wait_for_eof() -> None:
        try:
            while os.read(fd, 65536):
                pass
        except OSError:  # an unreadable stdin (GNU nohup gives it /dev/null opened write-only)
            return
        with contextlib.suppress(RuntimeError):  # the loop has closed: the core stopped already
            loop.call_soon_threadsafe(at_eof)

    threading.Thread(target=wait_for_eof, name="badshop-stdin", daemon=True).start()


async def _serve(port: int) -> int:
    # Bind before the app exists: CoreApp sets the last run's autosave aside for its restore offer as soon
    # as it is made (Task 12), and a start that can't listen must leave it for the next one to offer.
    try:
        listener = socket.create_server(("127.0.0.1", port))
    except OSError as e:
        print(f"badshop-core: can't listen on 127.0.0.1:{port} ({e.strerror or e})", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(32)
    try:
        app = CoreApp(load_settings())
        server = await serve(app, token, sock=listener)  # from here on the server owns the socket
    except BaseException:
        listener.close()
        raise
    try:
        stop = _install_stop()  # before the handshake line: the shell may stop the core as soon as it reads it
        _stop_at_stdin_eof(stop)  # ... or die without stopping it
        print(json.dumps({"port": bound_port(server), "token": token}), flush=True)
        _stdout_to_stderr()
        await stop.wait()
    finally:
        server.close()  # every client gets 1001; each connection cancels the requests it still has open
        app.session.executor.cancel()  # a tool one of them is running stops now, not at its time limit
        await server.wait_closed()  # returns once every connection and every request has ended
        await app.close()  # stops the turn (as if the UI had closed), autosaves, closes the tool worker
    return 0


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return asyncio.run(_serve(a.port))  # a.cmd is "serve", the only command until Plan 5 adds "mcp"
```

`core/src/badshop/server/__main__.py`:
```python
from badshop.server.main import main

raise SystemExit(main())
```

(`multiprocessing`'s spawn start method never re-runs a package's `__main__` in the worker child, so
`python -m badshop.server` is safe with Task 10's worker; the console script's wrapper is guarded by
`if __name__ == "__main__"`.)

The signal handlers go in before the handshake line is printed: the desktop shell may stop the core as soon as it
has read the line, and a SIGTERM that arrived before `_install_stop()` would kill the process (exit -15, no autosave)
and a SIGINT would end in a `KeyboardInterrupt` traceback. On a stop, main closes the server (every client gets 1001,
and each connection cancels its open requests), stops a tool that is running at that moment (`cancel()` does
nothing when the worker is idle; without it the quit would wait for the tool, up to its 120 s limit), waits until
every connection and request has ended, and then closes the app: that stops the turn as if the UI had closed,
autosaves and closes the tool worker.

The end of stdin is the third way to stop (ruling R10, spec §5.7). The shell restarts a crashed core and kills it
when it quits, but a shell that crashes or is killed stops nothing, and the core would run on with no UI, holding
its port, its tool worker and the session. So the shell spawns the core with a stdin pipe it holds open and never
writes to: when the shell's process ends, however it ends, the OS closes its end of the pipe, stdin reaches end of
file, and `_stop_at_stdin_eof` sets the same `stop` event as SIGTERM. The core then stops the same clean way (every
client gets 1001, the turn stops, the session is autosaved, the worker is closed, exit 0) and says why on stderr.
Only a stdin that is not a terminal is watched: in a terminal, Ctrl-C is the way to stop it. The watcher is a
daemon thread calling `os.read` on the descriptor. `loop.connect_read_pipe` can't read an ordinary stdin pipe on
Windows and would switch a shared stdin to non-blocking mode, and a daemon thread blocked inside `sys.stdin`'s
buffered reader holds that reader's lock, which interpreter shutdown can then fail to take (a fatal "could not
acquire lock for <stdin>" at exit). An unreadable stdin (GNU `nohup` reopens a terminal's as /dev/null opened
write-only) fails the first read: there is nothing to watch, and the core runs until it is signalled, as `nohup`
intends. A stdin already at end of file (`< /dev/null`, or `badshop-core serve &` in a non-interactive shell, which
gets /dev/null) stops the core right after its handshake, so the README says to keep stdin open when scripting it.
`test_the_core_stops_cleanly_when_its_stdin_closes` pins this, and the tests' `core()` helper spawns every core
with a stdin pipe, as the shell does (pytest's own stdin may be /dev/null).

main binds the port before it makes the app. CoreApp sets the last run's autosave aside for spec §9's restore offer as
soon as it is made (Task 12: `project.claim_autosave()` moves it to `autosave/previous.badshop`), so a start that
can't listen has to fail before that: otherwise the file would sit as `previous.badshop`, and the next start, finding
no `session.badshop`, would offer nothing. `socket.create_server` binds and listens (on POSIX it sets `SO_REUSEADDR`
as asyncio's own `create_server` does; a port another socket listens on is still refused), and
`serve(app, token, sock=listener)` serves on that socket; from then on the server owns it, and `server.close()` closes
it. `test_a_busy_port_is_a_clean_error_and_changes_nothing` pins this: the last run's autosave is still
`session.badshop`, byte for byte, after a start on a busy port.

In `core/pyproject.toml`, replace:
```toml
[project.scripts]
badshop = "badshop.cli.main:main"
```
with:
```toml
[project.scripts]
badshop = "badshop.cli.main:main"
badshop-core = "badshop.server.main:main"
```

Then run `cd core && uv sync && uv lock --check`. A console script does not change `uv.lock` (CI's
`uv sync --locked` keeps passing); `uv sync` installs the `badshop-core` command into the project environment.

- [ ] **Step 5: Let `steps.replay_from` turn the cache off**

In `core/src/badshop/server/app.py`, replace:
```python
    async def _steps_replay_from(self, actor: str, step_id: str) -> list[dict]:
        steps = await self._blocking(lambda: self.session.replay_from(step_id))
        return [s.model_dump(mode="json") for s in steps]
```
with:
```python
    async def _steps_replay_from(self, actor: str, step_id: str, use_cache: bool = True) -> list[dict]:
        # use_cache=False runs every step again, even one whose inputs did not change (spec 2, criterion 4)
        steps = await self._blocking(lambda: self.session.replay_from(step_id, use_cache=use_cache))
        return [s.model_dump(mode="json") for s in steps]
```

The dispatcher builds each method's parameter schema from the handler's keyword parameters, so `use_cache` is an
optional boolean that defaults to `true`, and every existing caller is unchanged.

- [ ] **Step 6: Run the tests**

Run: `cd core && uv run pytest tests/test_server_ws.py -v`
Expected: `25 passed` in about 4 seconds, offline (13 test functions; `test_a_bad_hello_is_closed_with_1008` counts
once per bad hello, 13 of them). Four tests start core processes: the busy-port test one, the stdin test one, the
closing-the-UI test two (a run and the relaunch that restores its autosave), and the end-to-end test two. Then
`cd core && uv run pytest tests/test_server_app.py -q`: still `22 passed`. Then by hand:
`cd core && uv run badshop-core --version` prints `badshop-core 0.1.0`; `uv run badshop-core serve` prints one
line like `{"port": 40123, "token": "<a random token>"}` and waits; Ctrl-C ends it with exit status 0 and nothing else on
stdout. `uv run badshop-core serve < /dev/null; echo $?` prints the handshake line, then
`badshop-core: stdin closed (whoever started the core is gone); stopping` on stderr, and `0`.

- [ ] **Step 7: Update the docs**

`README.md`:

Edit 1. Replace:

```markdown
**Status:** the core engine and its `badshop` command line are built (Plan 1); the app
itself comes next. Start with the spec:
```

with:

```markdown
**Status:** the core engine and its `badshop` command line are built (Plan 1), and so is the
headless core the app will run: sessions, project files, the agent loop (driven by a scripted
stand-in model until Plan 3 adds real providers) and its local API (Plan 2). The app itself
comes next. Start with the spec:
```

Edit 2. Replace:

```markdown
`core/` holds the Python package (`core/src/badshop/`: `engine/`, `tools/`, `cli/`),
managed with [uv](https://docs.astral.sh/uv/). Run the CLI from the folder that holds your
images, since relative paths and the `badshop_work/` folder resolve against it:
```

with:

```markdown
`core/` holds the Python package (`core/src/badshop/`: `engine/`, `tools/`, `cli/`,
`session/`, `agent/`, `server/`), managed with [uv](https://docs.astral.sh/uv/). Run the
CLI from the folder that holds your images, since relative paths and the `badshop_work/`
folder resolve against it:
```

Edit 3. Replace:

```markdown
`reference/` holds the working CLI engine this app is built from (`badshop.py`, the
Claude Code skill that drives it, and a generated catalog of every tool and parameter).
```

with:

````markdown
`reference/` holds the working CLI engine this app is built from (`badshop.py`, the
Claude Code skill that drives it, and a generated catalog of every tool and parameter).

## Running the core

`badshop-core` is the headless core the desktop app talks to: it holds the session (images,
steps, replay, project files) and runs the tools and the agent.

```
uv run --project /path/to/badshop/core badshop-core serve
```

(`python -m badshop.server serve` in the project's environment does the same.) It listens on
127.0.0.1 only, on a free port (`--port N` picks one), and prints exactly one line to stdout,
`{"port": 40123, "token": "<a random token>"}`; everything else goes to stderr. A client connects to
`ws://127.0.0.1:<port>` and first sends `{"type": "hello", "token": "<token>", "actor": "user"}`.
The core answers `{"type": "welcome", "actor": "user", "version": "0.1.0"}`; any other first
message (or none within 10 s) closes the connection with code 1008. After that it is JSON-RPC
2.0 in text frames: requests such as
`{"jsonrpc": "2.0", "id": 1, "method": "tools.list", "params": {}}`, and events
(`step.finished`, `approval.needed`, `turn.finished` and the rest) as notifications. The
methods and events are listed in spec §7 and `core/src/badshop/server/app.py`. Requests run
concurrently, so match replies by `id`; messages can be up to 64 MiB, so raise your client's
limit (websockets' default is 1 MiB). Closing the connection cancels the requests it is still
waiting on. Ctrl-C or SIGTERM stops the core cleanly: clients get close code 1001, a running
tool and the agent's turn stop, and the session is autosaved. When stdin is not a terminal, the
end of stdin does the same: the app starts the core with a stdin pipe, so a core whose app has
died stops too. When you script it, keep its stdin open: with stdin from `/dev/null` (which a
background job in a script gets) it stops right after the handshake line.

Until Plan 3 adds real model providers, `chat.send` plays a script: point
`BADSHOP_FAKE_PROVIDER` (or the `fake_provider_script` setting) at a JSON list of replies such
as `[{"text": "Looking for faces.", "tool_calls": [{"name": "find", "arguments": {"image": "a3f9c1d2"}}]}]`.
Settings live in the config folder (`$BADSHOP_CONFIG_DIR` overrides it), and the open session
autosaves to `autosave/session.badshop` in the data folder. On the next start the core sets that
file aside as `autosave/previous.badshop` and offers it: `session.get` reports its path as
`restorable`, and `session.restore` opens it (spec §9).
````

`docs/superpowers/plans/2026-09-26-roadmap.md` (row 2 of the table):

Edit 1. Replace:

```markdown
| 2 | Sessions and local server | §13.2 | `session/` (artifacts by SHA-256, steps, replay with remapping and cache, `.badshop` project files, autosave) as a `Store`; `server/` WebSocket JSON-RPC API and events (spec §7); scripted fake provider; headless agent loop skeleton | not yet written |
```

with:

```markdown
| 2 | **Sessions and local server** | §13.2 | `session/` (artifacts by SHA-256, steps, replay with remapping and cache, `.badshop` project files, autosave) as a `Store`; `server/` WebSocket JSON-RPC API and events (spec §7); scripted fake provider; headless agent loop skeleton | done: `2026-09-27-plan-2-sessions-server.md`; what Plan 3 and later inherit is in `2026-09-27-plan-1-carry-forward.md` |
```

`docs/superpowers/plans/2026-09-27-plan-1-carry-forward.md`:

Edit 1. Replace:

```markdown
**Written:** 2026-09-27, at the end of Plan 1's final fix wave.
```

with:

```markdown
**Written:** 2026-09-27, at the end of Plan 1's final fix wave. **Updated** at the end of Plan 2
(its Task 13): every Plan 2 item below is done, and Plans 3 to 6 gained the items Plan 2 hands on.
```

Edit 2. Replace:

```markdown
## Plan 2: sessions and local server

These are contracts. Plan 1 left the engine seams in place (`EngineResult.data`, the `Store`
protocol, `assets.URL_POLICY`), but nothing uses them yet.
```

with:

```markdown
## Plan 2: sessions and local server

**Done** (Plan 2, `2026-09-27-plan-2-sessions-server.md`). Where each item landed:

| Item | Done in |
|---|---|
| SP F3 manifest and progress | Task 4: `engine/manifest.py` (`ASSETS`, `status`, `download`, `ensure_rembg_model`), `assets.PROGRESS`; rembg weights download through `cached()`, so pooch never prints. Task 12: `assets.status`, `assets.download`, `asset.progress` events |
| SP F4 provenance | Task 3: `EngineResult.data["sources"]`, aligned with `outputs`; Tasks 5 and 7 store it as `ArtifactMeta.source`. Its last part (the original as the downloaded bytes) is declined: see Declined below |
| SP F15 validate / execute | Task 2: `runner.validate(name, raw, actor)`, `runner.execute(name, params, store, stem)`; `run_tool` composes them |
| SEC-S7 untrusted callers | Task 2: `runner.validate` checks the actor; Task 5: `ArtifactStore.resolve` takes ids only and never touches the disk; Task 7: `Session.export` by artifact id through `files.final_path`, `ToolSpec.writes_files`; Task 11: approvals keyed on `read_only`; Task 12: only `user` may call session, file and settings methods |
| SEC-S8 clipboard | Task 2: `FetchParams.clipboard` is user-only (the `USER_ONLY` marker in `engine/types.py`): hidden from `llm_schema`, refused from other actors |
| SEC-S2 private addresses | Task 6: `session/netpolicy.py` (`refuse_private`, `guarded`) around every tool call. Resolve-then-connect stays best effort (no address pinning) |
| SEC-S4 worker with limits | Task 10: `session/worker.py` (`WorkerExecutor`: 120 s wall clock, 3072 MB RSS watchdog, cancel, a fresh worker after any kill) |
| CO M8 prep flattens | Task 5: `ArtifactStore.import_image` keeps alpha; `prep` stays the parity tool |
| TRI T7 F3 rembg sessions | Task 4: `cutout.rembg_session` caches one session per model in the worker; `drop_sessions()` |
| Task 3 GIF handles | Task 5: imports and artifacts decode from bytes |
| The four parked residuals (Plan 1 rulings 80-83) | Task 1: `finish.GIF_MAX_STILL_MS`, `text.DOWNLOAD_RETRY_S`, `common.check_size(w, h, floor)`; the golden-output note stays under Plan 6 below |

The entries below are the record of what was asked.
```

Edit 3. Replace:

```markdown
  paths only from the UI's file picker. The registry has no way yet to hide a field from
  `llm_schema`; add one (it also serves SEC-S8).
```

with:

```markdown
  paths only from the UI's file picker. Plan 2 added the way to hide a field from the model:
  `json_schema_extra={USER_ONLY: True}` drops it from `llm_schema` and refuses it from every
  actor but `user` (as `FetchParams.clipboard` does). The marker lives in `engine/types.py`, which
  engine modules such as `engine/text.py` import it from (`tools/registry` re-exports it, but the
  engine must not import `tools`).
```

Edit 4. Replace:

```markdown
  *Plan 3 must:* mark web-originated text in tool results as untrusted data (delimited, with a
  system-prompt rule not to follow instructions inside it).
```

with:

```markdown
  *Plan 3 must:* mark web-originated text in tool results as untrusted data (delimited, with a
  system-prompt rule not to follow instructions inside it).

- **Plan 2: real providers.** Plan 2 drives the turn loop with `agent/fake.ScriptedProvider`
  only; with no script set, `chat.send` answers "no model provider is set up yet".
  *Plan 3 must:* implement `agent/provider.Provider` (`async complete(messages, tools, on_delta)
  -> Reply`, OpenAI chat format) with LiteLLM, add provider profiles, keyring secrets, capability
  checks and the `providers.*` RPC methods, and give each provider its actor name
  `agent:<provider>`.

- **Plan 2: image budgeting.** `agent/context.build_messages` gives the model images only as text
  placeholders (`image_placeholder`: `[image a3f9c1d2: lincoln_work, 761x1000]`).
  *Plan 3 must:* add spec §5.4's budget: the latest output and any artifact the model referenced
  this turn as image parts downscaled to at most 1024 px, older ones as placeholders the model
  reopens with `view`.

- **Plan 2: the system prompt is a placeholder.** `agent/context.SYSTEM_PROMPT` only states the
  product rules and that image refs are artifact ids.
  *Plan 3 must:* replace it with the prompt adapted from `reference/SKILL.md` (spec §5.4), and
  reword the finish tools' descriptions (SP F14 above) in the same pass.

- **Plan 2: tool results are the CLI's lines.** The model's tool result is
  `session/session.result_text(step, artifacts)`: artifact lines plus the tool's `lines`, and `find`'s
  lines carry CLI flag syntax (`--fit-box`, `cutout --oval --box`).
  *Plan 3 must:* also give the model the step's `data` (JSON: `find`'s boxes and points), so it
  copies numbers instead of reading CLI hints.

- **Plan 2: no `provider.status` events.** Spec §7 lists `provider.status`, but Plan 2's only
  provider is the scripted one, and nothing sends the event.
  *Plan 3 must:* define its payload and send it from the real providers (for example a missing
  key, a failed capability check, a local server that does not answer).

- **Plan 2: no retry-turn method.** Spec §10 ends a turn that hits a provider error with a
  banner and a "retry turn" action. Plan 2's loop already ends such a turn with
  `turn.finished {"reason": "provider_error", "error"}` and leaves `SessionData.transcript` as
  it stood (the user's message last), but no method runs the turn again.
  *Plan 3 must:* add that method (for example `chat.retry {}`) together with the real provider
  errors.

- **Plan 2: no images in the transcript.** `SessionData.transcript`, the provider-format history
  the agent resumes from, is saved inside `session.json`, and a project whose `session.json`
  passes 16 MiB (`session/project.MAX_SESSION_BYTES`) can't be saved ("too big to open again").
  Plan 2's transcript holds text only (images appear as `image_placeholder` text).
  *Plan 3 must:* never put base64 images in `SessionData.transcript`: keep artifact ids or
  placeholders there, and build the image parts from the artifacts each time it sends a request.
```

Edit 5. Replace:

```markdown
  *Plan 4 (or whoever next touches `cli/argparse_gen.py`):* append `(default X; A-B)` from each
  FieldInfo, and consider `choices` for small bounded int ranges, as the reference had.
```

with:

```markdown
  *Plan 4 (or whoever next touches `cli/argparse_gen.py`):* append `(default X; A-B)` from each
  FieldInfo, and consider `choices` for small bounded int ranges, as the reference had.

- **Plan 2: talking to the core.** `badshop-core serve` prints exactly one stdout line,
  `{"port": N, "token": "<token>"}`, then points stdout at stderr, so the log (and anything a library
  prints) is on stderr. A connection's first message is the hello with the token and actor
  `user`; replies can come out of order (requests run concurrently); messages go up to 64 MiB.
  Closing a connection cancels the requests it is still waiting on (a session call already
  running finishes, and the reconnected UI sees its step). When the last `user` connection
  closes, the core stops a running turn and rejects pending approvals, so a reload of the webview
  ends the turn. SIGINT and SIGTERM stop the core cleanly (clients get 1001, a running tool is
  stopped, the session is autosaved), and the core installs those handlers before it prints the
  handshake line. When its stdin is not a terminal, the core also stops that way once stdin
  reaches end of file, so a core whose shell died without stopping it stops too (spec §5.7).
  *Plan 4 must:* spawn the core with a stdin pipe that the shell holds open for the core's whole
  life and never writes to (not `/dev/null`, which stops the core at once), read the handshake
  line, give the token only to the webview, call `session.get` after every (re)connect to
  rebuild the UI's state, and log stderr (spec §9).

- **Plan 2: restoring the autosave.** The session autosaves to `autosave/session.badshop` in the
  data folder after every change. When the core starts, it sets the last run's autosave aside
  (`session/project.claim_autosave()` moves it to `autosave/previous.badshop`, so this run's
  first change can't overwrite it); the snapshot reports that path as `restorable` (`null` when
  there is none), and the user-only `session.restore {}` opens it as an unsaved session
  (`path: null`).
  *Plan 4 must:* show spec §9's offer to restore it when `session.get` after launch has
  `restorable`, and call `session.restore` if the user takes it (after restarting a crashed
  core, spec §10, call it without asking).

- **Plan 2: two additions to spec §7.** The event `step.deleted {"step_id"}`: `steps.delete`
  sends it once the step is gone (Task 8's `delete_last`; the step's artifacts stay in the
  session). And the user-only method `session.restore {}` with the snapshot key `restorable`
  (the entry above). Spec §7 does not list either yet.
  *Plan 4 must:* drop the step from the timeline on `step.deleted`, and treat both as part of
  the protocol.

- **Plan 2: no `step.progress` events.** Spec §7 lists `step.progress`, but Plan 2 never sends
  it: a step announces `step.started`, then `step.finished` or `step.failed`. Downloads inside a
  tool (the first cutout fetching its model) already report `asset.progress {name, done, total}`.
  *Plan 4 must:* show a running step without it (for example its elapsed time), or add it: the
  worker already forwards download progress to the core over its pipe (Task 10), and a tool's
  own progress could travel the same way and leave through `Session`'s `emit`.

- **Plan 2: asset downloads restart from zero.** Spec §10 says asset downloads can be resumed.
  `assets.cached()` downloads into a new `.part` file every time, so an interrupted download
  starts over (about 973 MB for birefnet-general).
  *Plan 4 must:* with spec §8.6's first-run pre-download, make downloads resumable (keep the
  partial file, continue it with an HTTP Range request, check the hash at the end).

- **Plan 2: `assets.download` can't be cancelled mid-file.** It runs `manifest.download` in a
  thread that nothing can stop: a client that disconnects, or a cancelled request, leaves the
  download running to the end of the file.
  *Plan 4 must:* add a cancel (for example a flag that `cached()` checks between chunks, set by
  an `assets.cancel {name}` method) before it offers a Cancel button on a download.

- **Plan 2: the `approved` step status is unused.** Spec §6 lists `approved`, but Plan 2 moves
  an approved step from `proposed` straight to `running` and announces the decision with
  `approval.resolved {"step_id", "decision", "note"}`. The status still exists
  (`session.RUNNABLE` accepts it, and a step saved as `approved` reopens as `error`).
  *Plan 4 may:* use it (for example for a step approved but queued behind a running one); until
  a plan does, the UI must not wait for a step to become `approved`.
```

Edit 6. Replace:

```markdown
## Plan 6: packaging and release CI
```

with:

```markdown
## Plan 5: MCP proxy and CLI agents

- **Plan 2: the proxy's side of the API.** The WebSocket accepts the hello actors `cli:claude`,
  `cli:codex` and `cli:gemini` (`server/ws.ACTOR`). Those connections receive every event and
  may call only the methods open to any actor (`tools.list`, which gives them `llm_schema`,
  `tools.run`, which runs as their actor, and `artifacts.get`); the rest answer `-32001`. A CLI
  actor's `tools.run` already waits on the approval gate like the in-app agent's calls (spec §7),
  and if the proxy disconnects while it waits, the step is rejected.
  *Plan 5 must:* add `badshop-core mcp --connect <ws-url> --token <t> --actor cli:<name>` as a
  second subcommand in `server/main.py`, and keep the MCP tool call alive (progress
  notifications or heartbeats) while an approval takes minutes.

## Plan 6: packaging and release CI
```

Edit 7. Replace:

```markdown
  runner) fails only in `test_golden`, compare that runner's CPU before regenerating.
```

with:

```markdown
  runner) fails only in `test_golden`, compare that runner's CPU before regenerating.

- **Plan 2: the tool worker is a spawn-context process.** `session/worker.py` starts a fresh
  Python for tools; a frozen core would start itself again instead.
  *Plan 6 must:* call `multiprocessing.freeze_support()` first thing in the frozen entry point,
  and keep the per-OS smoke test running one tool (spec §11 runs `find`), which proves the
  worker starts.

- **Plan 2: stopping the core on Windows.** `badshop-core serve` stops cleanly on SIGINT and
  SIGTERM (`loop.add_signal_handler`, or `signal.signal` where the event loop has no signal
  handlers). Tauri kills a child with TerminateProcess on Windows, which skips the clean stop;
  the session is autosaved after every change, so nothing is lost. Closing the core's stdin pipe
  (Plan 4 spawns it with one) is a clean stop on every OS, Windows included.
  *Plan 6 must:* check on each OS that killing the core leaves no worker process behind.

- **Plan 2: birefnet-general's memory is unmeasured.** The tool worker stops a tool whose RSS
  passes 3072 MB (Task 10; the `tool_memory_mb` setting). In Task 4's prototype a u2net session
  took about 370 MB and its first `remove()` about 216 MB more; birefnet-general's weights are
  5.5 times u2net's (about 973 MB), and nobody has run it under the limit yet.
  *Measure it* when a plan first uses the model (a model picker, say), and *Plan 6 must* have
  done so at the latest: a cutout with `model=birefnet-general` on a 1000 px working copy, in the
  worker, on each release OS. If it passes 3072 MB, raise the default limit or say what the model
  needs where the user picks it.
```

Edit 8. Replace:

```markdown
## Declined
```

with:

```markdown
## Whichever plan first changes the project file

- **Plan 2: no schema migrations yet.** `session.json` carries `"schema": 1`
  (`session/models.SCHEMA`), and `project.open_project` refuses a newer schema. Spec §6 says
  older schemas are migrated, but nothing older than 1 exists, so there is no migration code.
  *That plan must:* bump `SCHEMA`, migrate schema 1 files when it opens them, and test the
  migration with a project saved at schema 1.

## Declined

- **SP F4 (last part): the original is the downloaded bytes.** Plan 2 stores a fetched picture
  as a working copy plus the tool's full-size output as its original (Task 7), and that output is
  the engine's encoding (JPEG candidates are re-encoded), not the bytes the server sent.
  Accepted: the provenance itself (`kind`, `url`, `page`, `title`, `license`, `creator`) is in
  `ArtifactMeta.source`.
```

- [ ] **Step 8: Run the whole suite**

Run: `cd core && uv run pytest -q && uv run ruff check .`
Expected: `1320 passed, 1 deselected` in about a minute and a half (Task 12's 1295 plus these 25; the deselected one
is the `network` test), and ruff prints `All checks passed!`.

- [ ] **Step 9: Commit**

From the repository root:
```bash
git add core/src/badshop/server/ws.py core/src/badshop/server/main.py core/src/badshop/server/__main__.py \
        core/src/badshop/server/app.py core/pyproject.toml core/tests/test_server_ws.py README.md \
        docs/superpowers/plans/2026-09-26-roadmap.md docs/superpowers/plans/2026-09-27-plan-1-carry-forward.md
git commit -m "feat(server): WebSocket transport, badshop-core entry point, end-to-end test and docs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Done when

- `cd core && uv run pytest -q` gives `1320 passed, 1 deselected` (the deselected test is the `network` one), `uv run pytest -m network -q` passes with internet, `uv run ruff check .` is clean, and `uv lock --check` passes.
- `uv run badshop-core serve` prints `{"port": ..., "token": ...}` as its first stdout line, accepts a `hello` with that token, and stops cleanly on SIGTERM or when its stdin closes.
- The end-to-end test in `tests/test_server_ws.py` passes. It imports two pictures, runs a scripted turn with an approval, saves, reopens, and replays to byte-identical artifacts (spec §2 success criterion 4, headless).
- Every "Plan 2 must" item in `docs/superpowers/plans/2026-09-27-plan-1-carry-forward.md` is marked done or re-owned, and the roadmap marks Plan 2 done. That is Plan 3's input.

## How this plan was checked

Each task was drafted from a controller design brief, prototyped in a private clone, and verified against the real Plan 1 code by a second agent, then revised. The plan was then cross-checked for interface consistency and spec coverage. Finally, all 13 tasks were dry-run in order in one clone, and three defects that only showed up there were fixed: lone Unicode surrogates in remote text, hostile step ids in project files, and a Stop that could be lost before a tool started. A last pass re-applied every section to the Plan 1 merge commit (`e4a9869`) and got a tree byte-identical to the dry run's, with each section's stated test count matching at its point in the sequence.

---

## Appendix: decisions made while writing this plan

These rulings settled the drafters' open questions. They are already reflected in the tasks above.

**Fixes folded into the tasks:**

- R1 (Task 5, Task 7): Task 5 owns `ArtifactStore.import_image(data, label, source=None, *, produced_by=None)`
  (both halves credited to `produced_by`). Task 7 drops its step that patches `session/artifacts.py` and
  just uses the keyword.
- R2 (Task 1): the animate guard compares in the GIF writer's units (Pillow writes `int(ms / 10)` as a
  16-bit number): refuse when `still * p.delay // 10 > GIF_MAX_STILL_MS // 10` (keep the cheap
  pre-filter). Add a boundary test: 78 frames x 8402 ms (655_356 ms) is accepted like the reference,
  a still of 655_360 ms or more is refused.
- R3 (Task 4): raise the floor to `rembg[cpu]>=2.0.85` in pyproject (asset_path relies on
  `BaseSession.model_dir()` and the `models/<name>` layout; 2.0.85 is the locked version). `uv lock`
  must not move any other package.
- R4 (Task 6): `execute_call`'s JSON coercion also replaces non-finite floats (NaN, inf) with None, so
  the JSON-RPC layer never sends a value a JavaScript client can't parse. Test it.
- R5 (Task 7, test in Task 11): `Session.import_image` appends a change note (for example
  `"the user added image a3f9c1d2 (lincoln_work)"`) so the agent hears about images the user adds
  without attaching them to a message (spec §5.3). Task 11 gets a test that the next turn's system note
  mentions it.
- R6 (Task 8, test in Task 9): `referenced_ids()` also keeps the outputs of every step that a message's
  `step_ids` names (deleted steps included) and every artifact whose short id (first 8 hex) appears in the
  transcript's text, so a reopened session never loses a picture the chat or the model still points at
  (Review Focus 2, save side). Task 9 tests: delete_last, save, open, and the deleted step's output is
  still present.
- R7 (Task 8, Task 12): `delete_last` emits `step.deleted {"step_id": ...}` (an addition to spec §7's
  event list, recorded in the carry-forward doc); Task 12 lists and forwards it.
- R8 (Task 10): after each call the worker child drops cached rembg sessions (`cutout.drop_sessions()`)
  when its own RSS is above half of `max_rss_mb` (carry-forward TRI T7 F3, "drop them under memory
  pressure"). Test with a tiny limit.
- R9 (Task 12): `Dispatcher.handle` treats `ValueError` and `RecursionError` from `json.loads` as
  PARSE_ERROR (-32700) — test with `'[' * 100_000`. Add app-level tests for switching the approval mode
  in the middle of a turn and for a CLI caller's gate following `session.data.approval_mode`.
- R10 (Task 13): `badshop-core serve` also stops cleanly (autosave, worker closed, exit 0) when its stdin
  reaches EOF and stdin is not a TTY — the shell spawns the core with a stdin pipe so an orphaned core
  can't outlive its shell (spec §5.7). Test: spawn with `stdin=PIPE`, close it, expect exit 0 within a
  few seconds. The carry-forward edits must record these deferrals, each with its owner: `step.progress`
  events (Plan 4; downloads already report `asset.progress`), `provider.status` (Plan 3), a retry-turn
  method (Plan 3, with real provider errors), resumable asset downloads (Plan 4, first-run pre-download),
  the unused `approved` step status (Plan 4 may use it; Plan 2 goes proposed → running and announces
  approval with `approval.resolved`), schema migrations (none exist until the first schema bump),
  SP F4's "original is the downloaded bytes" (Plan 2 keeps the tool's full-size output as the original;
  accepted), Plan 3 must never put base64 images in `SessionData.transcript` (the 16 MiB session.json
  cap), `assets.download` cannot be cancelled mid-file (Plan 4), and birefnet-general's memory against
  the 3072 MB tool limit (measure when it is first used; Plan 6 at the latest). Also the new
  `step.deleted` event and the new `session.restore`/`restorable` API.
- R11: the plan file is `docs/superpowers/plans/2026-09-27-plan-2-sessions-server.md` (Task 13's roadmap
  and carry-forward edits use this name).

**Accepted as drafted:**
- Task 1: no floor for cutout's sticker border; the animate guard also applies to `-o` APNG/WebP.
- Task 2: the user may switch `clipboard` on while approving an agent's fetch (the user is trusted);
  USER_ONLY lives in engine/types.py.
- Task 3: Wikipedia lead images carry no licence yet (Plan 4 shows licences; fetch it then); Imgflip
  `page` stays None; provenance `url` is the requested link, not the post-redirect one.
- Task 4: `status()`/`asset_path()` import rembg in the calling process (about 200 MB, only when asked).
- Task 5: Pillow's DecompressionBombWarning on 89-100 Mpx imports is cosmetic.
- Task 6: a copied LAN link is refused under the network guard.
- Task 9: 16 MiB for session.json and 2 GiB in total are the product limits.
- Task 11/12: a cancelled CLI caller's approval is announced by the step's `step.finished` (rejected),
  not by an immediate `approval.resolved`.
- Task 13: the end-to-end test's cores autosave into the shared test cache.

- R12 (found in the dry run): remote text also has lone Unicode surrogates replaced (Task 3); `open_project` refuses step and message ids `Session` never makes (Task 9); and Stop reaches a step through its own cancel event, passed from the turn loop through `Session.run` to the executor, so a Stop that lands before the tool starts is never lost (Tasks 6, 7, 10, 11).
