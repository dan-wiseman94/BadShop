# Plan 1: Core engine, tool registry, CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-file reference CLI into the `badshop` Python package: pure engine modules, one tool registry that every later front end (LLM tools, MCP, UI forms, CLI) is generated from, and a `badshop` CLI that reproduces the reference's output pixels.

**Architecture:** `engine/` holds pure functions (`params + PIL images → EngineResult`), ported from `reference/badshop.py` with their pixel logic unchanged. `tools/` registers each engine function as a `ToolSpec` (Pydantic params model, LLM description, flags) and runs tools against a `Store` that loads inputs and saves outputs. `cli/` generates argparse from the registry and supplies a file-based `Store`, so the CLI is a thin adapter. Parity with the reference is proven by running both CLIs on the same inputs and comparing decoded pixels.

**Tech Stack:** Python 3.12, uv, Pillow, NumPy, OpenCV (`opencv-python-headless<5`), rembg, Pydantic v2, platformdirs, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-26-badshop-app-design.md` (read §3, §5.1, §5.2, §11, §12 before starting). Roadmap: `docs/superpowers/plans/2026-09-26-roadmap.md`.

## Global Constraints

- Python `>=3.12,<3.14`; manage everything with `uv` (`uv sync`, `uv run`), run from `core/`.
- Dependencies (exact floors): `pillow>=10.1`, `numpy>=1.26`, `opencv-python-headless>=4.8,<5` (5.x removed the Haar cascades used for cats), `rembg[cpu]`, `pydantic>=2.7,<3`, `platformdirs>=4`. Dev: `pytest>=8`, `ruff>=0.6`. Add nothing else in this plan.
- Product rules (spec §3): nearest-neighbor scaling, hard alpha, no blending, feathering, colour matching or shadows; no image-generation model ever touches pixels.
- **Port, don't redesign:** every pixel algorithm is copied from `reference/badshop.py`. The only intended pixel change is `deepfry`'s noise source (seeded, Task 11).
- Engine functions never print, never call `sys.exit`, never touch file paths: they raise `EngineError(message, hint)` and return `EngineResult`.
- rembg models offered are exactly `u2net` (default), `u2net_human_seg`, `isnet-anime`, `birefnet-general`. Never rely on rembg's own default model (`bria-rmbg`, historically non-commercial weights).
- Set `REMBG_HOME` (and `U2NET_HOME`) to the app data dir before importing rembg; never enable alpha matting.
- Downloaded assets (YuNet, fonts) go under `assets.data_dir()`: `$BADSHOP_DATA_DIR` if set, else `platformdirs.user_data_dir("badshop", appauthor=False)`.
- CLI defaults stay as in the reference: work files in `./badshop_work/`; finished files (`save`, `deepfry`, `animate`, `export`) in `$BADSHOP_OUT` or `~/Pictures/badshop/`, never overwriting.
- `reference/` is read-only. Never edit it.
- Commit after every task with a conventional-commit message ending in the line `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Odd image modes and phone photos** (CMYK JPEG, palette GIF, 16-bit PNG, EXIF-rotated JPEG). Every tool should accept them and treat them as the upright RGB(A) picture. Pinned in Task 3 (`test_load_image_modes`).
2. **Coordinates outside the image or inverted boxes** (`x2 < x1`, a paste far off-canvas, a cutout box entirely outside). These should clamp or fail with a clear `EngineError`, never a traceback. Pinned in Task 7 (`test_paste_off_canvas`, `test_cutout_box_outside`, `test_cutout_inverted_box`).
3. **Very large inputs** (a 6000×4000 phone photo). `prep` must produce a ≤1000 px working copy quickly, and `view` must cap its output size. Pinned in Task 5 (`test_prep_huge_image`) and Task 4 (`test_view_caps_size`).
4. **Offline or failing network** (sources, first-run downloads of fonts and YuNet). These should give an `EngineError` with a hint, not a traceback. Pinned in Task 3 (`test_cached_offline`) and Task 12 (`test_fetch_offline`).
5. **Unicode and spaces** in captions and file paths (`"PROBLEM, LIBURALS?? 😂"`, `old photo é.png`). These should work end to end. Pinned in Task 5 (`test_info_path_with_spaces`) and Task 6 (`test_text_unicode_parity`).

---

## File map

```
LICENSE                                   MIT licence (Task 1)
.github/workflows/core.yml                lint + tests on push (Task 1)
core/
  pyproject.toml, .python-version         package + tool config (Task 1)
  src/badshop/
    __init__.py, __main__.py              version; `python -m badshop` (Task 1)
    engine/
      errors.py    EngineError                                        (Task 3)
      result.py    Output, EngineResult (+ encoding)                  (Task 3)
      common.py    image helpers: load/to_rgb/grid/boxes/colour/jpeg  (Task 3)
      assets.py    data dir, http_get, cached downloads, rembg env    (Task 3)
      types.py     ImageRef/Point/Box/Spot/Color, Params base         (Task 4)
      basic.py     info, prep, view                                   (Task 4)
      text.py      fonts, wrapping, rendering, caption                (Task 6)
      cutout.py    cutout (+ dilate)                                  (Task 7)
      compose.py   paste                                              (Task 7)
      faces.py     YuNet + Haar, find                                 (Task 8)
      annotate.py  draw, censor, eyes                                 (Task 9)
      filters.py   filter, warp                                       (Task 9)
      garnish.py   flare, sparkle, watermark                          (Task 10)
      finish.py    save, deepfry, animate                             (Task 11)
      sources.py   fetch/wiki/emoji/template/clipboard                (Task 12)
    tools/
      __init__.py  imports catalog (populates REGISTRY)               (Task 4)
      registry.py  ToolSpec, REGISTRY, register, get, image_fields    (Task 4)
      context.py   Store protocol                                     (Task 4)
      runner.py    ToolRun, run_tool                                  (Task 4)
      catalog.py   every registration + LLM descriptions (grows per task)
    cli/
      filestore.py FileStore (paths, -o, final dir, export)           (Task 5)
      argparse_gen.py  registry → argparse                            (Task 5)
      main.py      entry point                                        (Tasks 1, 5, 13)
      recipes.py   history, recipe, run                               (Task 13)
  tests/
    conftest.py    Pair harness (reference vs new), image asserts     (Task 2)
    memstore.py    in-memory Store for unit tests                     (Task 4)
    fixtures/      lincoln.png, trump.png, emoji_joy.png, LICENSES.md,
                   make_fixtures.py, api/*.json, api/page.html        (Tasks 2, 12)
    test_*.py      one file per task
```

---

### Task 1: Scaffold the package

**Files:**
- Create: `LICENSE`, `.github/workflows/core.yml`, `core/pyproject.toml`, `core/.python-version`, `core/src/badshop/__init__.py`, `core/src/badshop/__main__.py`, `core/src/badshop/cli/__init__.py`, `core/src/badshop/cli/main.py`, `core/tests/test_smoke.py`
- Modify: `.gitignore` (append `core/.test-cache/`)

**Interfaces:**
- Produces: `badshop.__version__ == "0.1.0"`; `badshop.cli.main.main(argv: list[str] | None = None) -> int`; `python -m badshop` exits with `main()`'s return value.

- [ ] **Step 1: Write the project files**

`core/pyproject.toml`:
```toml
[project]
name = "badshop"
version = "0.1.0"
description = "Deliberately bad, old-internet photoshops, art-directed by any LLM"
requires-python = ">=3.12,<3.14"
license = "MIT"
dependencies = [
    "pillow>=10.1",
    "numpy>=1.26",
    "opencv-python-headless>=4.8,<5",  # 5.x dropped the Haar cascades used for cat faces
    "rembg[cpu]",
    "pydantic>=2.7,<3",
    "platformdirs>=4",
]

[project.scripts]
badshop = "badshop.cli.main:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/badshop"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "models: needs downloaded ML models (rembg, YuNet); cached in core/.test-cache",
    "network: talks to real internet services",
]
addopts = "-m 'not network'"

[tool.ruff]
line-length = 110
target-version = "py312"
```

`core/.python-version`:
```
3.12
```

`core/src/badshop/__init__.py`:
```python
"""badshop: deliberately bad, old-internet photoshops."""

__version__ = "0.1.0"
```

`core/src/badshop/__main__.py`:
```python
from badshop.cli.main import main

raise SystemExit(main())
```

`core/src/badshop/cli/__init__.py`: empty file.

`core/src/badshop/cli/main.py` (Task 5 replaces the body; this is the minimal entry point):
```python
"""`badshop` command line."""

import argparse
import sys

from badshop import __version__


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="badshop")
    p.add_argument("--version", action="version", version=f"badshop {__version__}")
    p.parse_args(argv)
    return 0
```

`LICENSE`: the standard MIT licence text with `Copyright (c) 2026 Dan Wiseman`.

`.github/workflows/core.yml`:
```yaml
name: core
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: core
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: actions/cache@v4
        with:
          path: core/.test-cache
          key: test-cache-${{ hashFiles('core/uv.lock') }}
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run pytest -q
```

Append to `.gitignore`:
```
core/.test-cache/
```

- [ ] **Step 2: Write the failing test**

`core/tests/test_smoke.py`:
```python
import subprocess
import sys

import badshop


def test_version_attribute():
    assert badshop.__version__ == "0.1.0"


def test_module_entry_point_prints_version():
    p = subprocess.run([sys.executable, "-m", "badshop", "--version"], capture_output=True, text=True)
    assert p.returncode == 0
    assert p.stdout.strip() == "badshop 0.1.0"
```

- [ ] **Step 3: Sync and run the tests**

Run: `cd core && uv sync && uv run pytest tests/test_smoke.py -v`
Expected: both PASS (the files from Step 1 already implement it; if `uv sync` fails, fix the pyproject before continuing).

- [ ] **Step 4: Lint**

Run: `cd core && uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add LICENSE .gitignore .github core/pyproject.toml core/.python-version core/uv.lock core/src core/tests
git commit -m "chore: scaffold badshop core package

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Fixtures and the reference-parity harness

**Files:**
- Create: `core/tests/fixtures/make_fixtures.py`, `core/tests/fixtures/LICENSES.md`, `core/tests/fixtures/lincoln.png`, `core/tests/fixtures/trump.png`, `core/tests/fixtures/emoji_joy.png` (generated), `core/tests/conftest.py`, `core/tests/test_harness.py`

**Interfaces:**
- Produces (pytest fixtures and helpers every later task uses):
  - `pair` fixture → `Pair` with `.ref(*args, check=True) -> CompletedProcess`, `.new(*args, check=True) -> CompletedProcess`, `.ref_dir`, `.new_dir` (each a fresh cwd holding copies of the fixture PNGs), `.assert_same(rel_ref: str, rel_new: str | None = None)`
  - `assert_same_image(a: Path, b: Path)`: same size, frame count and RGBA bytes per frame
  - `FIXTURES: Path`, `TEST_CACHE: Path`, `cli_env(cwd: Path) -> dict[str, str]` (named so pytest never collects it as a test)

- [ ] **Step 1: Write the fixture generator (one-time, needs internet)**

`core/tests/fixtures/make_fixtures.py`:
```python
"""Regenerate the committed test images. Needs internet. Run: uv run python tests/fixtures/make_fixtures.py"""

import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
UA = {"User-Agent": "badshop-tests/0.1 (fixture generator)"}
COMMONS = {  # both public domain; see LICENSES.md
    "lincoln.png": "Abraham Lincoln head on shoulders photo portrait.jpg",
    "trump.png": "Donald Trump official portrait.jpg",
}
TWEMOJI_JOY = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/1f602.png"


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def commons_thumb(title: str, width: int = 600) -> bytes:
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": f"File:{title}",
                                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": width})
    pages = json.loads(get(f"https://commons.wikimedia.org/w/api.php?{q}"))["query"]["pages"]
    return get(next(iter(pages.values()))["imageinfo"][0]["thumburl"])


def main() -> None:
    for name, title in COMMONS.items():
        im = Image.open(io.BytesIO(commons_thumb(title))).convert("RGB")
        im.thumbnail((600, 600))
        im.save(HERE / name)
        print(name, im.size)
    Image.open(io.BytesIO(get(TWEMOJI_JOY))).convert("RGBA").save(HERE / "emoji_joy.png")
    print("emoji_joy.png")


if __name__ == "__main__":
    main()
```

`core/tests/fixtures/LICENSES.md`:
```markdown
# Test fixture sources

- `lincoln.png`: Alexander Gardner, 1863, "Abraham Lincoln head on shoulders photo portrait.jpg",
  Wikimedia Commons. Public domain (published before 1929).
- `trump.png`: "Donald Trump official portrait.jpg", Wikimedia Commons. Public domain (work of
  the US federal government).
- `emoji_joy.png`: Twemoji 1f602, © Twitter/X and contributors (jdecked/twemoji fork), CC-BY 4.0.
- `api/*`: recorded API responses from Wikimedia Commons, Openverse, Wikipedia and Imgflip,
  kept only as parser fixtures (Task 12).
```

Run: `cd core && uv run python tests/fixtures/make_fixtures.py`
Expected: prints `lincoln.png (…, 600)`, `trump.png (…, 600)`, `emoji_joy.png`; three PNGs now exist in `core/tests/fixtures/`.

- [ ] **Step 2: Write the harness**

`core/tests/conftest.py`:
```python
"""Shared fixtures. The `pair` fixture runs the reference CLI and the new CLI side by side."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageSequence

CORE = Path(__file__).resolve().parents[1]
REPO = CORE.parent
REFERENCE = REPO / "reference" / "badshop.py"
FIXTURES = Path(__file__).parent / "fixtures"
TEST_CACHE = CORE / ".test-cache"  # persistent across runs so models and fonts download once


def cli_env(cwd: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "XDG_CACHE_HOME": str(TEST_CACHE / "xdg"),     # reference: fonts + YuNet
        "BADSHOP_DATA_DIR": str(TEST_CACHE / "data"),  # new engine: fonts + YuNet
        "REMBG_HOME": str(TEST_CACHE / "rembg"),
        "U2NET_HOME": str(TEST_CACHE / "rembg"),
        "BADSHOP_OUT": str(cwd / "final"),
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def _run(cmd: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, env=cli_env(cwd), capture_output=True, text=True, timeout=900)
    if check:
        assert p.returncode == 0, f"{cmd}\n--- stdout\n{p.stdout}\n--- stderr\n{p.stderr}"
    return p


def frames(path: Path) -> tuple[list[bytes], tuple[int, int]]:
    im = Image.open(path)
    return [f.convert("RGBA").tobytes() for f in ImageSequence.Iterator(im)], im.size


def assert_same_image(a: Path, b: Path) -> None:
    fa, sa = frames(a)
    fb, sb = frames(b)
    assert sa == sb, f"size {sa} != {sb} ({a} vs {b})"
    assert len(fa) == len(fb), f"{len(fa)} frames != {len(fb)}"
    for i, (x, y) in enumerate(zip(fa, fb)):
        assert x == y, f"frame {i} pixels differ: {a} vs {b}"


class Pair:
    def __init__(self, root: Path):
        self.ref_dir, self.new_dir = root / "ref", root / "new"
        for d in (self.ref_dir, self.new_dir):
            d.mkdir()
            for f in FIXTURES.glob("*.png"):
                shutil.copy(f, d / f.name)

    def ref(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run([sys.executable, str(REFERENCE), *args], self.ref_dir, check)

    def new(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run([sys.executable, "-m", "badshop", *args], self.new_dir, check)

    def assert_same(self, rel_ref: str, rel_new: str | None = None) -> None:
        assert_same_image(self.ref_dir / rel_ref, self.new_dir / (rel_new or rel_ref))


@pytest.fixture
def pair(tmp_path: Path) -> Pair:
    return Pair(tmp_path)
```

Note: the reference runs with the core environment's Python (`sys.executable`), not its own PEP 723 environment, so both sides use identical library versions. That is what makes byte-level parity possible.

- [ ] **Step 3: Write the harness tests**

`core/tests/test_harness.py`:
```python
from PIL import Image

from conftest import FIXTURES, assert_same_image


def test_fixtures_exist_and_are_small():
    for name in ("lincoln.png", "trump.png"):
        im = Image.open(FIXTURES / name)
        assert max(im.size) <= 600
    assert Image.open(FIXTURES / "emoji_joy.png").mode == "RGBA"


def test_reference_runs(pair):
    out = pair.ref("info", "lincoln.png").stdout
    w, h = Image.open(FIXTURES / "lincoln.png").size
    assert out.strip() == f"lincoln.png: {w}x{h}"


def test_assert_same_image_detects_difference(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (4, 4), "red").save(a)
    Image.new("RGB", (4, 4), "red").save(b)
    assert_same_image(a, b)
    Image.new("RGB", (4, 4), "blue").save(b)
    try:
        assert_same_image(a, b)
    except AssertionError:
        return
    raise AssertionError("difference not detected")
```

- [ ] **Step 4: Run them**

Run: `cd core && uv run pytest tests/test_harness.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/tests
git commit -m "test: fixtures and reference-parity harness

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Engine foundations (errors, results, image helpers, assets)

**Files:**
- Create: `core/src/badshop/engine/__init__.py` (empty), `errors.py`, `result.py`, `common.py`, `assets.py`; `core/tests/test_foundations.py`

**Interfaces:**
- Produces:
  - `EngineError(message: str, hint: str | None = None)` with `.message`, `.hint`
  - `Output(key: str, image: Image, name_hint: str, fmt: str = "PNG", quality: int | None = None, frames: list[Image] | None = None, duration: int | None = None, caption: str = "")` with `.ext() -> str` and `.encode() -> bytes`
    - `name_hint`: a CLI default path relative to `badshop_work/` (may contain `{stem}`, includes the extension), or `"final:<stem>"` (no extension) for the finished-output folder
  - `EngineResult(outputs: list[Output] = [], lines: list[str] = [], data: dict = {})`
  - `common`: `load_image(src: Path | bytes) -> Image`, `to_rgb(im) -> Image`, `has_alpha(im) -> bool`, `font(size)`, `label(draw, xy, text, fnt)`, `draw_grid(im, major=100, minor=50) -> Image`, `clamp_box(box, size) -> tuple[int,int,int,int]`, `rgb(color: str) -> tuple[int,int,int]`, `int_box(box, W, H)`, `overlap(a, b) -> float`, `jpeg_cycle(im, quality) -> Image`, `need_cv2() -> (cv2, np)`
  - `assets`: `USER_AGENT`, `data_dir() -> Path`, `http_get(url, timeout=30) -> tuple[bytes, str]`, `cached(name: str, url: str, progress: Callable[[int, int | None], None] | None = None) -> Path`, `configure_rembg() -> None`

- [ ] **Step 1: Write the failing tests**

`core/tests/test_foundations.py`:
```python
import io

import pytest
from PIL import Image

from badshop.engine import assets, common
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output


def test_engine_error_carries_hint():
    e = EngineError("bad box", hint="use find")
    assert (e.message, e.hint, str(e)) == ("bad box", "use find", "bad box")


def test_output_encodes_png_jpeg_gif():
    im = Image.new("RGB", (8, 8), "red")
    assert Output("result", im, "result.png").encode()[:8] == b"\x89PNG\r\n\x1a\n"
    jpg = Output("saved", im, "final:x", fmt="JPEG", quality=20)
    assert jpg.ext() == ".jpg" and jpg.encode()[:2] == b"\xff\xd8"
    frames = [im.quantize(8), Image.new("RGB", (8, 8), "blue").quantize(8)]
    gif = Output("animated", frames[0], "final:x", fmt="GIF", frames=frames, duration=80)
    assert Image.open(io.BytesIO(gif.encode())).n_frames == 2


def test_engine_result_defaults_are_independent():
    a, b = EngineResult(), EngineResult()
    a.lines.append("x")
    assert b.lines == []


def test_clamp_box_sorts_and_clamps():
    assert common.clamp_box((50, 60, 10, 5), (40, 40)) == (10, 5, 40, 40)


def test_clamp_box_outside_raises_engine_error():
    with pytest.raises(EngineError) as e:
        common.clamp_box((500, 500, 600, 600), (100, 100))
    assert "outside" in e.value.message


def test_rgb_unknown_colour():
    assert common.rgb("#ff0000") == (255, 0, 0)
    with pytest.raises(EngineError):
        common.rgb("not-a-colour")


def test_draw_grid_keeps_size():
    im = Image.new("RGB", (320, 240), "white")
    g = common.draw_grid(im)
    assert g.size == im.size and g.getpixel((100, 5)) != (255, 255, 255)


@pytest.mark.parametrize("mode", ["CMYK", "P", "I;16", "LA", "F"])
def test_load_image_modes(tmp_path, mode):
    src = Image.new(mode, (30, 20))
    ext = {"CMYK": ".jpg", "P": ".gif", "I;16": ".png", "LA": ".png", "F": ".tiff"}[mode]
    path = tmp_path / f"x{ext}"
    src.save(path)
    im = common.load_image(path)
    assert common.to_rgb(im).mode == "RGB" and im.size == (30, 20)


def test_load_image_applies_exif_rotation(tmp_path):
    im = Image.new("RGB", (40, 20), "white")
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90° clockwise on display
    path = tmp_path / "phone.jpg"
    im.save(path, exif=exif)
    assert common.load_image(path).size == (20, 40)


def test_data_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    assert assets.data_dir() == tmp_path / "d"


def test_cached_downloads_once_and_reports_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 5000)
    seen = []
    p = assets.cached("sub/model.bin", src.as_uri(), progress=lambda done, total: seen.append(done))
    assert p.read_bytes() == b"x" * 5000 and seen and seen[-1] == 5000
    src.unlink()  # a second call must not touch the network
    assert assets.cached("sub/model.bin", src.as_uri()) == p


def test_cached_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "d"))
    with pytest.raises(EngineError) as e:
        assets.cached("f.ttf", "http://127.0.0.1:9/nothing-listens-here")
    assert e.value.hint and "internet" in e.value.hint
    assert not (tmp_path / "d" / "f.ttf").exists()


def test_configure_rembg_sets_home_without_overriding(monkeypatch, tmp_path):
    monkeypatch.delenv("REMBG_HOME", raising=False)
    monkeypatch.delenv("U2NET_HOME", raising=False)
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    assets.configure_rembg()
    import os
    assert os.environ["REMBG_HOME"] == str(tmp_path / "rembg")
    monkeypatch.setenv("REMBG_HOME", "/custom")
    assets.configure_rembg()
    assert os.environ["REMBG_HOME"] == "/custom"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_foundations.py -q`
Expected: collection errors (`ModuleNotFoundError: No module named 'badshop.engine'`).

- [ ] **Step 3: Implement**

`core/src/badshop/engine/errors.py`:
```python
class EngineError(Exception):
    """A failure the user or the model can act on. `hint` says what to try instead."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
```

`core/src/badshop/engine/result.py`:
```python
"""What every engine function returns."""

import io
from dataclasses import dataclass, field

from PIL import Image

EXT = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}


@dataclass
class Output:
    key: str  # printed label: "result", "work", "grid", "saved", "1"...
    image: Image.Image
    name_hint: str  # "result.png", "{stem}_work.png", "fetch/x_1.jpg", or "final:<stem>" (no extension)
    fmt: str = "PNG"
    quality: int | None = None
    frames: list[Image.Image] | None = None  # animated GIF frames; image is frames[0]
    duration: int | None = None
    caption: str = ""  # printed after the path on the same line

    def ext(self) -> str:
        return EXT[self.fmt]

    def encode(self) -> bytes:
        buf = io.BytesIO()
        if self.frames:
            self.frames[0].save(buf, "GIF", save_all=True, append_images=self.frames[1:],
                                duration=self.duration, loop=0, optimize=False)
        elif self.fmt == "JPEG":
            kw = {"quality": self.quality} if self.quality is not None else {}
            self.image.save(buf, "JPEG", **kw)
        else:
            self.image.save(buf, self.fmt)
        return buf.getvalue()


@dataclass
class EngineResult:
    outputs: list[Output] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
```

`core/src/badshop/engine/common.py`: port `reference/badshop.py` lines 99–169 with these exact changes:
- Replace `open_rgb(path)` with two functions:
  ```python
  def load_image(src: Path | bytes) -> Image.Image:
      """Open a file or bytes upright (EXIF rotation applied), fully loaded, mode preserved."""
      im = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src)
      im = ImageOps.exif_transpose(im)
      im.load()
      return im


  def to_rgb(im: Image.Image) -> Image.Image:
      if im.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):  # 16-bit: scale down, don't clip
          im = im.convert("I").point(lambda v: v * (1 / 256)).convert("L")
      return im.convert("RGB")
  ```
- Keep `has_alpha`, `font`, `label`, `draw_grid`, `rgb` verbatim, except `rgb` raises `EngineError(f"unknown color {color!r}", hint="use a name like red or a hex value like #ff00ff")` instead of `sys.exit`.
- `clamp_box`: verbatim, except the final check raises `EngineError(f"box {box} is empty or lies outside the {w}x{h} image", hint="boxes are X1 Y1 X2 Y2 in pixels of this image; use find or a grid view to get them")`.
- `need_cv2`: raise `EngineError("OpenCV is not installed", hint='pip install "opencv-python-headless<5" numpy')` instead of `sys.exit`.
- Move `overlap` and `int_box` (reference lines 635–646) and `jpeg_cycle` (lines 1186–1191) here verbatim.
- Drop `out_path`, `final_path`, `http_get`, `cached` (they move to `cli/filestore.py` and `assets.py`).
- Imports: `io`, `from pathlib import Path`, PIL modules, `from badshop.engine.errors import EngineError`.

`core/src/badshop/engine/assets.py`:
```python
"""Where downloaded assets live, and how they get there."""

import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import platformdirs

from badshop import __version__
from badshop.engine.errors import EngineError

USER_AGENT = f"badshop/{__version__} (open-source meme tool, run locally by its user)"
CHUNK = 64 * 1024


def data_dir() -> Path:
    env = os.environ.get("BADSHOP_DATA_DIR")
    return Path(env) if env else Path(platformdirs.user_data_dir("badshop", appauthor=False))


def http_get(url: str, timeout: float = 30) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "") or ""


def cached(name: str, url: str, progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Download `url` once into data_dir()/name and reuse it. Raises EngineError when offline."""
    path = data_dir() / name
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, part.open("wb") as fh:
            total = int(r.headers.get("Content-Length") or 0) or None
            done = 0
            while chunk := r.read(CHUNK):
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        part.unlink(missing_ok=True)
        raise EngineError(f"couldn't download {name} ({e})",
                          hint="check the internet connection; it is only downloaded once") from e
    part.replace(path)
    return path


def configure_rembg() -> None:
    """Point rembg's model cache at our data dir, unless the user already chose one. Call before import."""
    home = str(data_dir() / "rembg")
    os.environ.setdefault("REMBG_HOME", home)
    os.environ.setdefault("U2NET_HOME", os.environ["REMBG_HOME"])
```

- [ ] **Step 4: Run the tests**

Run: `cd core && uv run pytest tests/test_foundations.py -v`
Expected: all PASS. If `test_load_image_modes[F]` fails to save a TIFF, keep the case but save with `compression=None`.

- [ ] **Step 5: Commit**

```bash
git add core/src/badshop/engine core/tests/test_foundations.py
git commit -m "feat(engine): errors, results, image helpers and asset downloads

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Parameter types, tool registry, runner, and the first tools (info, prep, view)

**Files:**
- Create: `core/src/badshop/engine/types.py`, `core/src/badshop/engine/basic.py`, `core/src/badshop/tools/__init__.py`, `registry.py`, `context.py`, `runner.py`, `catalog.py`; `core/tests/memstore.py`, `core/tests/test_registry.py`

**Interfaces:**
- Consumes: Task 3 (`EngineError`, `Output`, `EngineResult`, `common.*`).
- Produces:
  - `types`: `ImageRef`, `Point`, `Box`, `Spot`, `Color` (Annotated aliases with JSON-schema `format` `badshop-image|badshop-point|badshop-box|badshop-spot|color`); `class Params(BaseModel)` (`extra="forbid"`) with optional ClassVars `POSITIONAL: tuple[str, ...]` and `FLAGS: dict[str, str]` (CLI metadata only)
  - `registry`: `ToolSpec(name, params, run, summary, description, category, mutates=True, network=False, read_only=False)`, `REGISTRY: dict[str, ToolSpec]`, `register(spec) -> ToolSpec`, `get(name) -> ToolSpec`, `image_fields(params_cls) -> dict[str, bool]` (field → is_list), `llm_schema(spec) -> dict`
    - `run` signature: `Callable[[Params, Store], EngineResult]`
  - `context`: `Store` protocol with `load(ref: str) -> Image`, `put(output: Output, stem: str) -> str`, `export(ref: str, name: str | None) -> str`
  - `runner`: `ToolRun(tool: str, params: Params, refs: list[str], result: EngineResult)`, `run_tool(name: str, raw: dict, store: Store) -> ToolRun`
  - `basic`: `InfoParams`, `info(p, image)`, `PrepParams`, `prep(p, image)`, `ViewParams`, `view(p, image)`
  - `tests/memstore.py`: `MemoryStore` (refs `mem:N`; `.images: dict[str, Image]`, `.outputs: dict[str, Output]`, `.add(image, name="x.png") -> str`)

- [ ] **Step 1: Write the failing tests**

`core/tests/memstore.py`:
```python
from pathlib import Path

from PIL import Image

from badshop.engine.errors import EngineError
from badshop.engine.result import Output


class MemoryStore:
    """In-memory Store for unit tests. Refs look like `mem:3/name.png` so stems stay meaningful."""

    def __init__(self):
        self.images: dict[str, Image.Image] = {}
        self.outputs: dict[str, Output] = {}
        self.exported: list[tuple[str, str | None]] = []

    def add(self, image: Image.Image, name: str = "x.png") -> str:
        ref = f"mem:{len(self.images)}/{name}"
        self.images[ref] = image
        return ref

    def load(self, ref: str) -> Image.Image:
        if ref not in self.images:
            raise EngineError(f"no such image: {ref}")
        return self.images[ref].copy()

    def put(self, output: Output, stem: str) -> str:
        ref = self.add(output.image, Path(output.name_hint.replace("{stem}", stem)).name)
        self.outputs[ref] = output
        return ref

    def export(self, ref: str, name: str | None) -> str:
        self.exported.append((ref, name))
        return f"exported/{name or 'x'}"
```

`core/tests/test_registry.py`:
```python
import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.tools import registry
from badshop.tools.runner import run_tool
from memstore import MemoryStore


@pytest.fixture
def store():
    return MemoryStore()


def test_basic_tools_registered():
    for name in ("info", "prep", "view"):
        spec = registry.get(name)
        assert spec.summary and len(spec.description) >= 40


def test_unknown_tool():
    with pytest.raises(EngineError):
        registry.get("nope")


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        registry.register(registry.get("info"))


def test_image_fields_and_schema_formats():
    spec = registry.get("prep")
    assert registry.image_fields(spec.params) == {"image": False}
    schema = registry.llm_schema(spec)
    assert schema["properties"]["image"]["format"] == "badshop-image"
    assert "POSITIONAL" not in schema["properties"]


def test_info(store):
    ref = store.add(Image.new("RGB", (30, 20)), "pic.png")
    run = run_tool("info", {"image": ref}, store)
    assert run.result.lines == [f"{ref}: 30x20"] and run.refs == []
    assert run.result.data == {"width": 30, "height": 20}


def test_prep_makes_work_and_grid(store):
    ref = store.add(Image.new("RGB", (3000, 1500), "white"), "big.png")
    run = run_tool("prep", {"image": ref}, store)
    keys = [o.key for o in run.result.outputs]
    assert keys == ["work", "grid"]
    assert store.images[run.refs[0]].size == (1000, 500)
    assert run.result.lines == ["size: 1000x500"]
    assert run.result.outputs[0].name_hint == "{stem}_work.png"


def test_view_caps_size(store):
    ref = store.add(Image.new("RGB", (4000, 2000), "white"), "huge.png")
    run = run_tool("view", {"image": ref, "grid": True}, store)
    assert store.images[run.refs[0]].size == (1024, 512)


def test_bad_params_become_engine_error_with_hint(store):
    ref = store.add(Image.new("RGB", (10, 10)))
    with pytest.raises(EngineError) as e:
        run_tool("prep", {"image": ref, "max": "big"}, store)
    assert "max" in e.value.hint
    with pytest.raises(EngineError):
        run_tool("prep", {"image": ref, "unknown_option": 1}, store)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'badshop.tools'`.

- [ ] **Step 3: Implement the types**

`core/src/badshop/engine/types.py`:
```python
"""Parameter types shared by every tool. The JSON-schema `format` drives UI widgets and CLI nargs."""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

ImageRef = Annotated[str, Field(json_schema_extra={"format": "badshop-image"})]
Point = Annotated[tuple[int, int], Field(json_schema_extra={"format": "badshop-point"})]
Box = Annotated[tuple[int, int, int, int], Field(json_schema_extra={"format": "badshop-box"})]
Spot = Annotated[tuple[int, int, int], Field(json_schema_extra={"format": "badshop-spot"})]  # x, y, radius
Color = Annotated[str, Field(json_schema_extra={"format": "color"})]


class Params(BaseModel):
    """Base for every tool's parameters. ClassVars are CLI metadata and never appear in the schema."""

    model_config = ConfigDict(extra="forbid")
    POSITIONAL: ClassVar[tuple[str, ...]] = ()  # fields that are positional on the CLI, in order
    FLAGS: ClassVar[dict[str, str]] = {}  # field -> CLI flag, when not --field-name
```

- [ ] **Step 4: Implement the registry, store protocol and runner**

`core/src/badshop/tools/registry.py`:
```python
"""The single list of tools. LLM tools, MCP, UI forms and the CLI are all generated from it."""

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: type[Params]
    run: Callable[[Any, Any], EngineResult]  # (params, store) -> result
    summary: str  # one line: CLI help, UI palette
    description: str  # for LLMs: what it does, when to use it, coordinate conventions
    category: str  # sources | inspect | cut | compose | text | effects | finish
    mutates: bool = True  # produces new images
    network: bool = False
    read_only: bool = False


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"tool {spec.name!r} is already registered")
    REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> ToolSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        raise EngineError(f"unknown tool {name!r}", hint=f"tools: {', '.join(sorted(REGISTRY))}") from None


def _is_image(annotation: Any) -> bool:
    for meta in getattr(annotation, "__metadata__", ()):
        extra = getattr(meta, "json_schema_extra", None) or {}
        if extra.get("format") == "badshop-image":
            return True
    return False


def image_fields(params_cls: type[Params]) -> dict[str, bool]:
    """Fields holding image references -> whether the field is a list of them."""
    found = {}
    for name, f in params_cls.model_fields.items():
        # A plain `x: ImageRef` field: pydantic merges the Annotated Field into the FieldInfo itself.
        if (f.json_schema_extra or {}).get("format") == "badshop-image":
            found[name] = False
            continue
        # list[ImageRef] / ImageRef | None keep the Annotated wrapper inside the annotation.
        for arg in typing.get_args(f.annotation):  # list[ImageRef], Optional[ImageRef]
            if _is_image(arg):
                found[name] = typing.get_origin(f.annotation) is list
    return found


def llm_schema(spec: ToolSpec) -> dict:
    return spec.params.model_json_schema()
```

`core/src/badshop/tools/context.py`:
```python
from typing import Protocol

from PIL import Image

from badshop.engine.result import Output


class Store(Protocol):
    """Where tool inputs come from and outputs go. The CLI uses files; sessions (Plan 2) use artifacts."""

    def load(self, ref: str) -> Image.Image: ...

    def put(self, output: Output, stem: str) -> str: ...

    def export(self, ref: str, name: str | None) -> str: ...
```

`core/src/badshop/tools/runner.py`:
```python
from dataclasses import dataclass
from pathlib import PurePath

from pydantic import ValidationError

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import Params
from badshop.tools.context import Store
from badshop.tools.registry import get, image_fields


@dataclass
class ToolRun:
    tool: str
    params: Params
    refs: list[str]  # stored outputs, same order as result.outputs
    result: EngineResult


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

`core/src/badshop/tools/__init__.py`:
```python
from badshop.tools import catalog as _catalog  # noqa: F401  (registers every tool)
from badshop.tools.registry import REGISTRY, ToolSpec, get

__all__ = ["REGISTRY", "ToolSpec", "get"]
```

- [ ] **Step 5: Implement the basic engine tools**

`core/src/badshop/engine/basic.py`:
```python
"""Inspection and working copies."""

from typing import ClassVar

from PIL import Image
from pydantic import Field

from badshop.engine.common import draw_grid, to_rgb
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import ImageRef, Params


class InfoParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to measure")


def info(p: InfoParams, image: Image.Image) -> EngineResult:
    return EngineResult(lines=[f"{p.image}: {image.width}x{image.height}"],
                        data={"width": image.width, "height": image.height})


class PrepParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to make a working copy of")
    max: int = Field(1000, ge=16, description="longest side in px (default 1000)")


def prep(p: PrepParams, image: Image.Image) -> EngineResult:
    # reference/badshop.py cmd_prep: same resize, same grid
    im = to_rgb(image)
    w, h = im.size
    scale = min(1.0, p.max / max(w, h))
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    return EngineResult(
        outputs=[Output("work", im, "{stem}_work.png"), Output("grid", draw_grid(im), "{stem}_work_grid.png")],
        lines=[f"size: {im.width}x{im.height}"],
    )


class ViewParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to look at")
    grid: bool = Field(False, description="overlay labeled pixel gridlines for reading coordinates")
    max: int = Field(1024, ge=64, le=4096, description="longest side of the returned view in px")


def view(p: ViewParams, image: Image.Image) -> EngineResult:
    im = image.convert("RGBA") if image.mode in ("RGBA", "LA", "P") else to_rgb(image)
    w, h = im.size
    scale = min(1.0, p.max / max(w, h))
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    if p.grid:
        im = draw_grid(im.convert("RGB"))
    note = "" if scale == 1 else f" (scaled {scale:.3f}; multiply by {1 / scale:.3f} for source pixels)"
    return EngineResult(outputs=[Output("view", im, "{stem}_view.png")], lines=[f"size: {im.width}x{im.height}{note}"])
```

`core/src/badshop/tools/catalog.py` (later tasks append to this file; keep one `register(...)` call per tool):
```python
"""Every tool, registered once, with the description an LLM sees."""

from badshop.engine import basic
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="info", params=basic.InfoParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: basic.info(p, s.load(p.image)),
    summary="print an image's size",
    description="Report an image's width and height in pixels. Cheap; use it before choosing coordinates.",
))

register(ToolSpec(
    name="prep", params=basic.PrepParams, category="inspect",
    run=lambda p, s: basic.prep(p, s.load(p.image)),
    summary="make a small working copy plus a gridded copy",
    description=("Make a working copy no larger than `max` px on its longest side, plus a copy with labeled "
                 "pixel gridlines. Work only with the working copy afterwards so coordinates you read "
                 "match what the tools use."),
))

register(ToolSpec(
    name="view", params=basic.ViewParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: basic.view(p, s.load(p.image)),
    summary="look at an image, optionally with a coordinate grid",
    description=("Return an image so you can see it. Set grid=true to overlay labeled pixel gridlines "
                 "(every 50 px, labels every 100) when you need to read coordinates. Views larger than "
                 "`max` are scaled down and say so; convert coordinates back before using them."),
))
```

Note: `view` has `mutates=False` but still returns an output (the rendered view). `mutates` means "adds a new image to the work": the CLI gives `-o` only to mutating tools, and the session (Plan 2) uses the flag to decide what the timeline shows as a result.

- [ ] **Step 6: Run the tests**

Run: `cd core && uv run pytest tests/test_registry.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add core/src/badshop core/tests/memstore.py core/tests/test_registry.py
git commit -m "feat(tools): parameter types, registry, runner, and info/prep/view

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: File store, argparse generator, CLI entry point

**Files:**
- Create: `core/src/badshop/cli/filestore.py`, `core/src/badshop/cli/argparse_gen.py`; `core/tests/test_cli.py`
- Modify: `core/src/badshop/cli/main.py` (replace body)

**Interfaces:**
- Consumes: Task 4 (`REGISTRY`, `ToolSpec`, `run_tool`, `Store`), Task 3 (`load_image`, `EngineError`, `Output`).
- Produces:
  - `FileStore(work_dir: Path, final_dir: Path, out: str | None = None)` implementing `Store`
  - `final_path(final_dir: Path, stem: str, ext: str) -> Path` (never overwrites: `stem.ext`, `stem_2.ext`, …)
  - `add_tool_parser(sub, spec: ToolSpec) -> None`; parsed namespaces carry `_tool` (tool name) and `_out` (the `-o` value or `None`)
  - `cli.main.WORK_DIR = Path("badshop_work")`, `cli.main.final_dir() -> Path`, `cli.main.build_parser() -> ArgumentParser`, `cli.main.main(argv) -> int`

- [ ] **Step 1: Write the failing tests**

`core/tests/test_cli.py`:
```python
import shutil

from PIL import Image


def test_info_parity(pair):
    assert pair.new("info", "lincoln.png").stdout == pair.ref("info", "lincoln.png").stdout


def test_prep_parity(pair):
    assert pair.new("prep", "lincoln.png").stdout == pair.ref("prep", "lincoln.png").stdout
    pair.assert_same("badshop_work/lincoln_work.png")
    pair.assert_same("badshop_work/lincoln_work_grid.png")


def test_prep_out_parity(pair):
    pair.ref("prep", "trump.png", "--max", "300", "-o", "small.png")
    pair.new("prep", "trump.png", "--max", "300", "-o", "small.png")
    pair.assert_same("small.png")
    pair.assert_same("small_grid.png")


def test_prep_huge_image(pair):
    Image.new("RGB", (6000, 4000), "gray").save(pair.new_dir / "phone.jpg")
    out = pair.new("prep", "phone.jpg").stdout
    assert "size: 1000x667" in out


def test_info_path_with_spaces(pair):
    shutil.copy(pair.new_dir / "lincoln.png", pair.new_dir / "old photo é.png")
    out = pair.new("info", "old photo é.png").stdout
    assert out.startswith("old photo é.png: ")


def test_missing_file_is_a_clean_error(pair):
    p = pair.new("info", "missing.png", check=False)
    assert p.returncode == 1
    assert "no such image: missing.png" in p.stderr and "hint:" in p.stderr
    assert "Traceback" not in p.stderr


def test_bad_value_is_a_clean_error(pair):
    p = pair.new("prep", "lincoln.png", "--max", "3", check=False)
    assert p.returncode == 1 and "max" in p.stderr and "Traceback" not in p.stderr


def test_help_lists_tools(pair):
    out = pair.new("--help").stdout
    for name in ("info", "prep", "view"):
        assert name in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_cli.py -q`
Expected: failures (`invalid choice: 'info'` from the Task 1 stub parser).

- [ ] **Step 3: Implement the file store**

`core/src/badshop/cli/filestore.py`:
```python
"""Store implementation for the CLI: refs are file paths."""

import re
import shutil
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output


def final_path(final_dir: Path, stem: str, ext: str) -> Path:
    """Finished files never overwrite older ones: stem.ext, stem_2.ext, stem_3.ext..."""
    final_dir.mkdir(parents=True, exist_ok=True)
    p, i = final_dir / f"{stem}{ext}", 2
    while p.exists():
        p, i = final_dir / f"{stem}_{i}{ext}", i + 1
    return p


def clean_stem(stem: str) -> str:
    return re.sub(r"_(work|result)$", "", stem)


class FileStore:
    def __init__(self, work_dir: Path, final_dir: Path, out: str | None = None):
        self.work_dir, self.final_dir, self.out = work_dir, final_dir, out
        self._count = 0

    def load(self, ref: str) -> Image.Image:
        path = Path(ref)
        if not path.is_file():
            raise EngineError(f"no such image: {ref}", hint="check the path; outputs are printed as `key: path` lines")
        try:
            return load_image(path)
        except (UnidentifiedImageError, OSError) as e:
            raise EngineError(f"{ref} isn't an image this tool can read ({e})") from None

    def put(self, output: Output, stem: str) -> str:
        first = self._count == 0
        self._count += 1
        if self.out and first:
            path = Path(self.out)
        elif self.out:  # secondary outputs sit next to -o: small.png -> small_grid.png
            o = Path(self.out)
            path = o.with_name(f"{o.stem}_{output.key}{output.ext()}")
        elif output.name_hint.startswith("final:"):
            path = final_path(self.final_dir, output.name_hint[6:].replace("{stem}", clean_stem(stem)), output.ext())
        else:
            path = self.work_dir / output.name_hint.replace("{stem}", stem)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(output.encode())
        return str(path)

    def export(self, ref: str, name: str | None) -> str:
        src = Path(ref)
        if not src.is_file():
            raise EngineError(f"no such image: {ref}")
        dest = final_path(self.final_dir, name or clean_stem(src.stem), src.suffix)
        shutil.copyfile(src, dest)
        return str(dest)
```

Note: `prep -o small.png` names its grid `small_grid.png`, exactly as the reference does (`work.with_name(work.stem + "_grid.png")`).

- [ ] **Step 4: Implement the argparse generator**

`core/src/badshop/cli/argparse_gen.py`:
```python
"""Build argparse subcommands from tool parameter models."""

import argparse
import types
import typing
from typing import Any, Literal

from badshop.tools.registry import ToolSpec

METAVARS = {2: ("X", "Y"), 3: ("X", "Y", "R"), 4: ("X1", "Y1", "X2", "Y2")}


def _unwrap(t: Any) -> Any:
    """Strip Annotated and Optional wrappers."""
    while True:
        if typing.get_origin(t) is typing.Annotated:
            t = typing.get_args(t)[0]
        elif typing.get_origin(t) in (typing.Union, types.UnionType):
            args = [a for a in typing.get_args(t) if a is not type(None)]
            t = args[0]
        else:
            return t


def _classify(annotation: Any) -> tuple[str, Any]:
    t = _unwrap(annotation)
    origin = typing.get_origin(t)
    if t is bool:
        return "bool", None
    if origin is Literal:
        return "choice", list(typing.get_args(t))
    if origin is tuple:
        return "tuple", len(typing.get_args(t))
    if origin is list:
        kind, inner = _classify(typing.get_args(t)[0])
        return "list_" + kind, inner
    return "scalar", t


def _optional(annotation: Any) -> bool:
    return typing.get_origin(annotation) in (typing.Union, types.UnionType) and type(None) in typing.get_args(annotation)


def add_tool_parser(sub: argparse._SubParsersAction, spec: ToolSpec) -> None:
    model = spec.params
    s = sub.add_parser(spec.name, help=spec.summary, description=spec.summary)
    for name, f in model.model_fields.items():
        kind, inner = _classify(f.annotation)
        kw: dict[str, Any] = {"help": f.description or "", "default": argparse.SUPPRESS}
        if kind == "choice":
            kw.update(choices=inner, type=type(inner[0]))
        elif kind == "list_choice":
            kw.update(choices=inner, type=type(inner[0]))
        elif kind == "tuple":
            kw.update(type=int, nargs=inner, metavar=METAVARS[inner])
        elif kind == "list_tuple":
            kw.update(type=int, nargs=inner, metavar=METAVARS[inner], action="append")
        elif kind == "list_scalar":
            kw.update(type=inner)
        elif kind == "scalar":
            kw.update(type=inner)
        if name in model.POSITIONAL:
            if kind.startswith("list_"):
                kw["nargs"] = "+" if f.is_required() else "*"
                kw.pop("action", None)
            elif _optional(f.annotation):
                kw["nargs"] = "?"
            s.add_argument(name, **kw)
            continue
        flag = model.FLAGS.get(name, "--" + name.replace("_", "-"))
        if kind == "bool":
            s.add_argument(flag, dest=name, action="store_true", help=kw["help"], default=argparse.SUPPRESS)
        else:
            if kind in ("list_scalar", "list_choice"):
                kw["action"] = "append"
            s.add_argument(flag, dest=name, **kw)
    if spec.mutates:
        s.add_argument("-o", "--out", dest="_out", default=None, help="path for the main output")
    s.set_defaults(_tool=spec.name)
```

- [ ] **Step 5: Replace the CLI entry point**

`core/src/badshop/cli/main.py`:
```python
"""`badshop` command line: one subcommand per registered tool."""

import argparse
import os
import sys
from pathlib import Path

from badshop import __version__
from badshop.cli.argparse_gen import add_tool_parser
from badshop.cli.filestore import FileStore
from badshop.engine.errors import EngineError
from badshop.tools import REGISTRY
from badshop.tools.runner import run_tool

WORK_DIR = Path("badshop_work")


def final_dir() -> Path:
    return Path(os.environ.get("BADSHOP_OUT") or Path.home() / "Pictures" / "badshop")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="badshop", description="Deliberately bad, old-internet photoshops.")
    p.add_argument("--version", action="version", version=f"badshop {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    for spec in REGISTRY.values():
        add_tool_parser(sub, spec)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    raw = {k: v for k, v in vars(a).items() if k not in ("cmd", "_tool", "_out")}
    store = FileStore(WORK_DIR, final_dir(), getattr(a, "_out", None))
    try:
        run = run_tool(a._tool, raw, store)
    except EngineError as e:
        print(e.message, file=sys.stderr)
        if e.hint:
            print(f"hint: {e.hint}", file=sys.stderr)
        return 1
    for ref, out in zip(run.refs, run.result.outputs):
        print(f"{out.key}: {ref}" + (f" {out.caption}" if out.caption else ""))
    for line in run.result.lines:
        print(line)
    return 0
```

- [ ] **Step 6: Run the tests**

Run: `cd core && uv run pytest tests/test_cli.py tests/test_smoke.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add core/src/badshop/cli core/tests/test_cli.py
git commit -m "feat(cli): file store and argparse generated from the registry

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Text (Impact, MS Paint, WordArt)

**Files:**
- Create: `core/src/badshop/engine/text.py`, `core/tests/test_text.py`
- Modify: `core/src/badshop/tools/catalog.py` (append registration)

**Interfaces:**
- Consumes: `common.rgb`, `common.to_rgb`, `common.font`, `assets.cached`, `assets.data_dir`.
- Produces: `TextParams`, `caption(p: TextParams, image) -> EngineResult`; `load_font(style: str, size: int, explicit: str | None = None) -> tuple[FreeTypeFont, str]`, `find_font_file`, `wrap_text`, `render_text`, `rainbow` (Task 10's watermark uses `load_font`).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_text.py`:
```python
import pytest

CASES = [
    ["problem, liburals??"],
    ["hand drawn", "--style", "paint", "--at", "300", "400", "--rotate", "10", "--color", "blue"],
    ["Four score and\\nseven covfefes", "--style", "wordart", "--bottom"],
    ["tiny", "--size", "18", "--margin", "4"],
]


@pytest.mark.parametrize("args", CASES)
def test_text_parity(pair, args):
    ref = pair.ref("text", "lincoln.png", *args).stdout
    new = pair.new("text", "lincoln.png", *args).stdout
    assert new == ref
    pair.assert_same("badshop_work/result.png")


def test_text_unicode_parity(pair):
    args = ["text", "trump.png", "PROBLEM, LIBURALS?? 😂 ünïcödé", "-o", "u.png"]
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("u.png")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_text.py -q`
Expected: FAIL (`invalid choice: 'text'`).

- [ ] **Step 3: Port the module**

Create `core/src/badshop/engine/text.py` by porting `reference/badshop.py` lines 189–302 (fonts section: `FONT_DIRS`, `FONT_CANDIDATES`, `FONT_DOWNLOADS`, `find_font_file`, `load_font`, `wrap_text`, `rainbow`, `render_text`) and `cmd_text` (lines 926–953), with these changes and nothing else:
- `FONT_DIRS`: replace the last entry `CACHE_DIR / "fonts"` with `assets.data_dir() / "fonts"`. `find_font_file` is `lru_cache`d, so compute the list inside a helper `_font_dirs()` called at lookup time, so tests that change `BADSHOP_DATA_DIR` see the right folder.
- In `find_font_file`, the download branch calls `assets.cached(f"fonts/{name}", FONT_DOWNLOADS[name])` and catches `EngineError` (not `Exception`) to keep going down the list when offline.
- `render_text` uses `common.rgb` (already raises `EngineError`).
- `cmd_text(a)` becomes:
  ```python
  class TextParams(Params):
      POSITIONAL: ClassVar = ("image", "text")
      image: ImageRef = Field(description="image to caption")
      text: str = Field(description="the words; a literal \\n forces a line break")
      style: Literal["impact", "paint", "wordart"] = Field(
          "impact", description="impact: white, black outline, uppercase; paint: colored with a hard "
                                "shadow; wordart: rainbow face with a 3D extrusion")
      bottom: bool = Field(False, description="bottom caption (default is top)")
      at: Point | None = Field(None, description="center the text on this point instead")
      size: int | None = Field(None, ge=4, description="font size in px (default: fits the image width)")
      color: Color | None = Field(None, description="paint text color (default red), or wordart extrusion color (default purple)")
      rotate: float = Field(0, description="degrees counter-clockwise")
      margin: int = Field(20, ge=0, description="gap from the edge in px")
      font: str | None = Field(None, description="path or name of a font file to use instead")


  def caption(p: TextParams, image: Image.Image) -> EngineResult:
      im = to_rgb(image)
      # ...lines 928-946 of the reference verbatim, with `a.` replaced by `p.`...
      im.paste(layer, (x, y), layer)
      return EngineResult(
          outputs=[Output("result", im, "result.png")],
          lines=[f"text: {len(lines)} line(s), {p.style} style, font {used}, size {size}px, at top-left ({x}, {y})"],
      )
  ```

Append to `core/src/badshop/tools/catalog.py` (add `from badshop.engine import text` at the top with the other imports):
```python
register(ToolSpec(
    name="text", params=text.TextParams, category="text",
    run=lambda p, s: text.caption(p, s.load(p.image)),
    summary="Impact caption, MS Paint text, or WordArt",
    description=("Write a caption. Default: Impact meme style, white with black outline, uppercase, "
                 "auto-sized, at the top; bottom=true for the punchline. style=paint is colored text with a "
                 "hard shadow (looks drawn in MS Paint); style=wordart is a rainbow face with a 3D "
                 "extrusion. at=[x,y] centers the text anywhere. A literal \\n forces a line break."),
))
```

- [ ] **Step 4: Run the tests**

Run: `cd core && uv run pytest tests/test_text.py -v`
Expected: all PASS. If a parity test fails only for `wordart`/`impact`, compare the `font …` part of both stdouts: both sides must resolve the same font file. The reference downloads Anton into `.test-cache/xdg/badshop/fonts`, and the new side into `.test-cache/data/fonts`; both are the same upstream file.

- [ ] **Step 5: Commit**

```bash
git add core/src/badshop/engine/text.py core/src/badshop/tools/catalog.py core/tests/test_text.py
git commit -m "feat(engine): text captions, paint text and WordArt

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Cutout and paste

**Files:**
- Create: `core/src/badshop/engine/cutout.py`, `core/src/badshop/engine/compose.py`, `core/tests/test_cutout_paste.py`
- Modify: `core/src/badshop/tools/catalog.py`

**Interfaces:**
- Consumes: `common.clamp_box`, `common.has_alpha`, `common.rgb`, `common.to_rgb`, `assets.configure_rembg`.
- Produces: `CutoutParams`, `cutout(p, image) -> EngineResult` (output key `cutout`, hint `{stem}_cutout.png`, `data={"coverage": float}`); `dilate(alpha, n)`; `PasteParams`, `paste(p, base, piece) -> EngineResult` (output key `result`, hint `result.png`).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_cutout_paste.py`:
```python
import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from memstore import MemoryStore


@pytest.mark.models
def test_cutout_rembg_parity(pair):
    args = ["cutout", "trump.png", "--box", "120", "40", "480", "560"]
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("badshop_work/trump_cutout.png")


@pytest.mark.parametrize("extra", [["--oval"], ["--oval", "--sticker", "8"], ["--no-ai", "--sticker", "5",
                                                                              "--sticker-color", "yellow"]])
def test_cutout_no_model_parity(pair, extra):
    args = ["cutout", "trump.png", "--box", "150", "150", "450", "450", *extra, "-o", "c.png"]
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("c.png")


PASTES = [
    ["--fit-box", "100", "50", "400", "400", "--scale", "1.1", "--rotate", "3"],
    ["--at", "300", "580", "--anchor", "bottom", "--width", "200", "--height", "120", "--flip"],
    ["--repeat", "12", "--width", "60", "--region", "0", "300", "600", "600", "--seed", "4"],
]


@pytest.mark.parametrize("args", PASTES)
def test_paste_parity(pair, args):
    for side in (pair.ref, pair.new):
        side("paste", "lincoln.png", "emoji_joy.png", *args)
    pair.assert_same("badshop_work/result.png")


def test_paste_keeps_transparency():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (100, 100), (0, 128, 255)), "base.png")
    piece_im = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    piece_im.putpixel((5, 5), (255, 0, 0, 255))
    piece = store.add(piece_im, "piece.png")
    run = run_tool("paste", {"base": base, "piece": piece, "at": [0, 0], "width": 10}, store)
    out = store.images[run.refs[0]]
    assert out.getpixel((0, 0)) == (0, 128, 255) and out.getpixel((5, 5)) == (255, 0, 0)


def test_paste_off_canvas():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (50, 50), "white"), "b.png")
    piece = store.add(Image.new("RGBA", (10, 10), "red"), "p.png")
    run = run_tool("paste", {"base": base, "piece": piece, "at": [-5000, -5000], "width": 10}, store)
    assert store.images[run.refs[0]].getpixel((0, 0)) == (255, 255, 255)


def test_paste_needs_placement():
    store = MemoryStore()
    base = store.add(Image.new("RGB", (50, 50)), "b.png")
    piece = store.add(Image.new("RGBA", (10, 10)), "p.png")
    with pytest.raises(EngineError) as e:
        run_tool("paste", {"base": base, "piece": piece}, store)
    assert "width" in e.value.message


def test_cutout_box_outside():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError):
        run_tool("cutout", {"image": ref, "box": [100, 100, 200, 200], "no_ai": True}, store)


def test_cutout_inverted_box():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50), "red"), "x.png")
    run = run_tool("cutout", {"image": ref, "box": [40, 40, 10, 10], "no_ai": True}, store)
    assert store.images[run.refs[0]].size == (30, 30)


def test_cutout_rejects_unlisted_model():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (50, 50)), "x.png")
    with pytest.raises(EngineError):
        run_tool("cutout", {"image": ref, "model": "bria-rmbg"}, store)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_cutout_paste.py -q`
Expected: FAIL (`invalid choice: 'cutout'`, `unknown tool 'paste'`).

- [ ] **Step 3: Port cutout**

`core/src/badshop/engine/cutout.py`: port `dilate` (reference lines 808–817) verbatim and `cmd_cutout` (lines 819–870) as:
```python
RembgModel = Literal["u2net", "u2net_human_seg", "isnet-anime", "birefnet-general"]


class CutoutParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to cut from")
    box: Box | None = Field(None, description="rectangle to cut, pixel coords; omit to use the whole image")
    model: RembgModel = Field("u2net", description="background remover: u2net (default, fast), "
                              "u2net_human_seg (people), isnet-anime (cartoons), birefnet-general (cleaner)")
    threshold: int = Field(128, ge=0, le=255, description="alpha cutoff 0-255")
    grow: int = Field(0, ge=0, description="dilate the mask N px to drag in a halo of old background")
    no_ai: bool = Field(False, description="skip background removal; keep the whole rectangle")
    oval: bool = Field(False, description="cut a hard-edged ellipse filling the box instead (face-only swap)")
    sticker: int | None = Field(None, ge=1, description="add an N px flat outline around the shape")
    sticker_color: Color = Field("white", description="outline color for sticker")


def cutout(p: CutoutParams, image: Image.Image) -> EngineResult:
    src = image
    im = src.convert("RGBA") if has_alpha(src) else src.convert("RGB")
    # ...reference lines 824-866 verbatim with `a.` -> `p.`, and these two replacements:
    #   the rembg ImportError branch -> raise EngineError("rembg is not installed", hint='pip install "rembg[cpu]", or use no_ai')
    #   the `opaque is None` sys.exit -> raise EngineError("nothing was kept: the background remover found no subject in that box",
    #                                          hint="try a bigger box, a different model, or no_ai")
    # and call assets.configure_rembg() on the line before `from rembg import new_session, remove`.
    lines = [f"size: {piece.width}x{piece.height}", f"opaque: {coverage:.0%} of the cutout's bounding box"]
    if coverage < 0.15:
        lines.append("warning: very little was kept; the box may have missed the subject")
    return EngineResult(outputs=[Output("cutout", piece, "{stem}_cutout.png")], lines=lines,
                        data={"coverage": coverage})
```
(The first two statements replace the reference's `Image.open` + `exif_transpose`, because the store already loads images upright.)

- [ ] **Step 4: Port paste**

`core/src/badshop/engine/compose.py`: port `cmd_paste` (reference lines 872–924):
```python
class PasteParams(Params):
    POSITIONAL: ClassVar = ("base", "piece")
    base: ImageRef = Field(description="image to paste onto")
    piece: ImageRef = Field(description="cutout to paste")
    at: Point | None = Field(None, description="where the anchor goes, pixel coords")
    anchor: Literal["topleft", "center", "bottom"] = Field(
        "topleft", description="which point of the piece `at` refers to (bottom = bottom-center)")
    width: float | None = Field(None, gt=0, description="width to scale the piece to")
    height: float | None = Field(None, gt=0, description="height; omit to keep the aspect ratio")
    fit_box: Box | None = Field(None, description="instead of at/width: scale and center the piece to cover this box")
    scale: float = Field(1.0, gt=0, description="with fit_box, oversize factor (1.3 = 30% too big)")
    rotate: float = Field(0, description="degrees counter-clockwise")
    flip: bool = Field(False, description="mirror the piece horizontally")
    repeat: int | None = Field(None, ge=1, description="scatter this many random copies (0.5-1.5x width) instead")
    region: Box | None = Field(None, description="with repeat, only scatter inside this box")
    seed: int = Field(1, description="with repeat, change for a different scatter")


def paste(p: PasteParams, base_im: Image.Image, piece_im: Image.Image) -> EngineResult:
    base = to_rgb(base_im).convert("RGBA")
    piece = piece_im.convert("RGBA")
    # ...reference lines 876-957 verbatim with `a.` -> `p.`, except the two sys.exit calls become:
    #   raise EngineError("give width (or fit_box)", hint="fit_box covers a box; at + width places by a point")
    #   raise EngineError("give at (or fit_box, or repeat)", hint="at is where the anchor point goes")
    return EngineResult(outputs=[Output("result", base.convert("RGB"), "result.png")],
                        lines=[f"size: {base.width}x{base.height}", placed])
```

Append both registrations to `catalog.py` (import `cutout, compose`):
```python
register(ToolSpec(
    name="cutout", params=cutout.CutoutParams, category="cut",
    run=lambda p, s: cutout.cutout(p, s.load(p.image)),
    summary="crop a box and remove its background with hard edges",
    description=("Cut a piece out of an image. box is X1 Y1 X2 Y2; for a head use find's head box, generous "
                 "and cut across the neck. The background remover keeps the subject with a hard, jagged edge "
                 "on purpose. model=u2net_human_seg for people, isnet-anime for cartoons. oval=true cuts a "
                 "hard ellipse instead (face-only swap: use find's oval box). no_ai=true keeps the plain "
                 "rectangle. sticker=N adds a flat outline. If `opaque` is tiny, the box missed the subject."),
))

register(ToolSpec(
    name="paste", params=compose.PasteParams, category="compose",
    run=lambda p, s: compose.paste(p, s.load(p.base), s.load(p.piece)),
    summary="paste a cutout onto a base image",
    description=("Paste a cutout with nearest-neighbor scaling and no blending (the point of a bad "
                 "photoshop). Easiest: fit_box = the target's head box from find, scale 1.1. Or at + width "
                 "with an anchor (center for 'over the old head', bottom for 'standing on the ground'). "
                 "height squashes, rotate tilts (counter-clockwise), flip mirrors. repeat=N scatters N random "
                 "copies inside region (emoji rain, crowds). Each paste starts from the base you give it, so "
                 "to fix a placement re-run from the same base."),
))
```

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_cutout_paste.py -v`
Expected: all PASS (the `models` test downloads u2net once, ~170 MB, into `.test-cache/rembg`).

- [ ] **Step 6: Commit**

```bash
git add core/src/badshop/engine/cutout.py core/src/badshop/engine/compose.py core/src/badshop/tools/catalog.py core/tests/test_cutout_paste.py
git commit -m "feat(engine): cutout and paste

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Face finding

**Files:**
- Create: `core/src/badshop/engine/faces.py`, `core/tests/test_faces.py`
- Modify: `core/src/badshop/tools/catalog.py`

**Interfaces:**
- Consumes: `common.need_cv2`, `common.int_box`, `common.overlap`, `common.font`, `common.label`, `common.to_rgb`, `assets.cached`.
- Produces: `FindParams`, `find(p, image) -> EngineResult`. Output key `annotated`, hint `{stem}_faces.png`, caption `  (red = face, magenta = head, cyan = oval, green = eyes, yellow = nose/mouth, orange = chin)`. `data={"faces": [ {kind, score, box, head, oval, eyes, estimated, nose?, mouth?, chin?, roll?} ]}` with every tuple converted to a list (JSON-safe). No faces: no outputs, one line.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_faces.py`:
```python
import pytest
from PIL import Image

from badshop.tools.runner import run_tool
from memstore import MemoryStore
from conftest import FIXTURES


def _lines(out: str) -> list[str]:
    return [l for l in out.splitlines() if not l.startswith("annotated:")]


@pytest.mark.models
@pytest.mark.parametrize("image", ["lincoln.png", "trump.png"])
def test_find_parity(pair, image):
    ref, new = pair.ref("find", image).stdout, pair.new("find", image).stdout
    assert _lines(new) == _lines(ref)
    stem = image.removesuffix(".png")
    pair.assert_same(f"badshop_work/{stem}_faces.png")


@pytest.mark.parametrize("args", [["--detector", "haar"], ["--what", "cats"]])
def test_find_haar_parity(pair, args):
    assert _lines(pair.new("find", "lincoln.png", *args).stdout) == _lines(pair.ref("find", "lincoln.png", *args).stdout)


@pytest.mark.models
def test_find_data_is_json_safe():
    import json
    store = MemoryStore()
    ref = store.add(Image.open(FIXTURES / "lincoln.png").convert("RGB"), "lincoln.png")
    run = run_tool("find", {"image": ref}, store)
    faces = run.result.data["faces"]
    assert len(faces) == 1
    json.dumps(faces)
    (x1, y1), (x2, y2) = faces[0]["eyes"]
    assert x1 < x2 and 0 < y1 < 600


def test_find_nothing():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (200, 200), "white"), "blank.png")
    run = run_tool("find", {"image": ref, "detector": "haar"}, store)
    assert run.refs == [] and run.result.lines[0].startswith("nothing found")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_faces.py -q`
Expected: FAIL (`invalid choice: 'find'`).

- [ ] **Step 3: Port the module**

`core/src/badshop/engine/faces.py`: port reference lines 629–789 (`YUNET_URL`, `yunet_faces`, `haar_faces`, `cmd_find`) with:
- `yunet_faces` uses `assets.cached("face_detection_yunet_2023mar.onnx", YUNET_URL)`.
- `cmd_find(a)` becomes `find(p: FindParams, image)`:
  ```python
  class FindParams(Params):
      POSITIONAL: ClassVar = ("image",)
      image: ImageRef = Field(description="image to search")
      what: Literal["faces", "cats", "all"] = Field("faces", description="faces (human), cats, or all")
      detector: Literal["auto", "yunet", "haar"] = Field(
          "auto", description="auto: YuNet with landmarks, falling back to Haar cascades")
      min_score: float = Field(0.7, ge=0, le=1, description="YuNet confidence cutoff (lower finds more, and more junk)")
  ```
  - `im = to_rgb(image)` replaces `open_rgb(a.image)`.
  - Every `print(...)` in the body appends the same string to a local `lines` list instead, in the same order (including the `note: YuNet unavailable…` line).
  - `sys.exit(f"YuNet failed: {e}")` → `raise EngineError(f"YuNet failed: {e}", hint="use detector=haar")`.
  - The "nothing found" branch returns `EngineResult(lines=[f"nothing found in {p.image}; pick the box from the grid instead"], data={"faces": []})`.
  - The end returns:
    ```python
    legend = ("  (red = face, magenta = head, cyan = oval, green = eyes, "
              "yellow = nose/mouth, orange = chin)")
    return EngineResult(outputs=[Output("annotated", annotated, "{stem}_faces.png", caption=legend)],
                        lines=lines, data={"faces": [_jsonable(f) for f in kept]})
    ```
    with
    ```python
    def _jsonable(face: dict) -> dict:
        def conv(v):
            if isinstance(v, (tuple, list)):
                return [conv(x) for x in v]
            return float(v) if isinstance(v, float) else v
        return {k: conv(v) for k, v in face.items()}
    ```

Register in `catalog.py` (import `faces`):
```python
register(ToolSpec(
    name="find", params=faces.FindParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: faces.find(p, s.load(p.image)),
    summary="locate faces: head, face-oval, eyes, nose, mouth, chin and tilt",
    description=("Find faces and get exact coordinates instead of guessing: the head box (hair to neck; use "
                 "it to cut a head and as paste's fit_box on the target), the oval box (brows to chin; for "
                 "cutout oval=true), both eye points (for eyes, warp, censor), nose, mouth corners, chin, and "
                 "roll (tilt in degrees; paste rotate = piece roll - target roll to match). Faces are numbered "
                 "left to right. Returns an annotated image; check it when there is more than one face. "
                 "what=cats for cat faces. Finds nothing on cartoons and side views: use view with grid then."),
))
```

- [ ] **Step 4: Run the tests**

Run: `cd core && uv run pytest tests/test_faces.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/badshop/engine/faces.py core/src/badshop/tools/catalog.py core/tests/test_faces.py
git commit -m "feat(engine): face finding with YuNet landmarks and Haar fallback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Annotations and filters (draw, censor, eyes, filter, warp)

**Files:**
- Create: `core/src/badshop/engine/annotate.py`, `core/src/badshop/engine/filters.py`, `core/tests/test_annotate_filters.py`
- Modify: `core/src/badshop/tools/catalog.py`

**Interfaces:**
- Consumes: `common.rgb`, `common.to_rgb`, `common.clamp_box`, `common.need_cv2`.
- Produces: `DrawParams`/`draw`, `CensorParams`/`censor`, `EyesParams`/`eyes` in `annotate`; `FILTERS`, `FilterParams`/`apply_filters`, `WarpParams`/`warp` in `filters`. Every one takes `(p, image)` and returns output key `result`, hint `result.png`.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_annotate_filters.py`:
```python
import pytest

from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from memstore import MemoryStore
from PIL import Image

CASES = [
    ["draw", "lincoln.png", "--circle", "300", "250", "80", "--arrow", "550", "550", "350", "350",
     "--line", "0", "0", "100", "100", "--rect", "10", "10", "200", "120", "--color", "lime", "--width", "4"],
    ["censor", "lincoln.png", "--box", "200", "200", "400", "260"],
    ["censor", "lincoln.png", "--box", "200", "200", "400", "260", "--box", "0", "0", "50", "50", "--style", "bar"],
    ["censor", "lincoln.png", "--box", "200", "200", "400", "260", "--style", "blur", "--block", "6"],
    ["eyes", "lincoln.png", "--at", "260", "240", "--at", "340", "238"],
    ["eyes", "lincoln.png", "--at", "260", "240", "--angle", "30", "--size", "9", "--color", "cyan"],
    ["filter", "lincoln.png", "posterize", "sepia"],
    ["filter", "lincoln.png", "emboss", "solarize", "invert"],
    ["warp", "lincoln.png", "--at", "260", "240", "40", "--at", "340", "238", "40", "--strength", "0.8"],
    ["warp", "lincoln.png", "--at", "300", "300", "90", "--strength", "-0.5"],
]


@pytest.mark.parametrize("args", CASES, ids=lambda a: " ".join(a[:2] + a[-2:]))
def test_parity(pair, args):
    ref, new = pair.ref(*args).stdout, pair.new(*args).stdout
    if "--angle" not in args:  # the reference prints an explicit --angle as argparse's float (30.0)
        assert new == ref
    pair.assert_same("badshop_work/result.png")


def test_draw_needs_a_shape():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (20, 20)), "x.png")
    with pytest.raises(EngineError):
        run_tool("draw", {"image": ref}, store)


def test_censor_needs_a_box():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (20, 20)), "x.png")
    with pytest.raises(EngineError):
        run_tool("censor", {"image": ref, "box": []}, store)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_annotate_filters.py -q`
Expected: FAIL (`invalid choice`).

- [ ] **Step 3: Port annotate.py**

Port reference `cmd_draw` (955–980), `cmd_censor` (982–1000), `cmd_eyes` (1002–1030). Params:
```python
class DrawParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to draw on")
    circle: list[Spot] = Field(default_factory=list, description="circles as X Y R; repeatable")
    arrow: list[Box] = Field(default_factory=list, description="arrows from X1 Y1 to X2 Y2 (head at the end)")
    line: list[Box] = Field(default_factory=list, description="lines X1 Y1 X2 Y2")
    rect: list[Box] = Field(default_factory=list, description="rectangles X1 Y1 X2 Y2")
    color: Color = Field("red", description="stroke color")
    width: int = Field(6, ge=1, description="stroke width in px")


class CensorParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to censor")
    box: list[Box] = Field(min_length=1, description="rectangles to censor; repeatable")
    style: Literal["pixelate", "bar", "blur"] = Field("pixelate", description="pixelate, black bar, or blur")
    block: int = Field(16, ge=1, description="pixel size for pixelate, blur radius for blur")


class EyesParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image with the face")
    at: list[Point] = Field(min_length=1, description="eye positions (use find's eye points); repeatable")
    angle: float = Field(155, description="beam direction in degrees, 0 = right, 90 = up")
    size: int | None = Field(None, ge=1, description="beam thickness in px (default: scaled to the image)")
    color: Color = Field("red", description="beam color")
```
Each function begins `im = to_rgb(image)` (eyes: `to_rgb(image).convert("RGBA")`), uses `p.` for `a.`, turns the draw `sys.exit` into `raise EngineError("nothing to draw", hint="give circle, arrow, line or rect")`, and ends with the reference's final `print` lines (after `result:`) as `lines`:
- draw: `[f"drew {n} shape(s) in {p.color}, {width}px"]`
- censor: `[f"censored {len(p.box)} region(s), style {p.style}"]`
- eyes: `[f"laser eyes at {[list(x) for x in p.at]}, angle {p.angle}, size {size}px"]`. The reference prints argparse's list-of-lists (`[[260, 240], [340, 238]]`), so convert the tuples to lists to keep identical stdout.

Format the angle with `{p.angle:g}`: that matches the reference's default output (`155`, argparse's untouched int default). An explicit `--angle 30` prints `30.0` in the reference and `30` here, so the test skips stdout comparison for that one case and still compares pixels.

- [ ] **Step 4: Port filters.py**

Port `FILTERS` and `cmd_filter` (1161–1184) and `cmd_warp` (1032–1047):
```python
FilterName = Literal["blur", "contour", "edges", "emboss", "grayscale", "invert", "oilpaint",
                     "posterize", "sepia", "sharpen", "solarize"]


class FilterParams(Params):
    POSITIONAL: ClassVar = ("image", "names")
    image: ImageRef = Field(description="image to filter")
    names: list[FilterName] = Field(min_length=1, description="filters to apply, in order")


class WarpParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to warp")
    at: list[Spot] = Field(min_length=1, description="spots as X Y R (center and radius); repeatable")
    strength: float = Field(0.6, description="positive bulges, negative pinches (1.0 is huge, -0.5 strong pinch)")
```
Lines: filter `[f"applied: {', '.join(p.names)}"]`; warp `[f"{'bulged' if p.strength > 0 else 'pinched'} {len(p.at)} spot(s), strength {p.strength:g}"]`. (The reference prints argparse's float, e.g. `0.8` and `-0.5`; `:g` gives the same.)

Register all five in `catalog.py` (import `annotate, filters`):
```python
register(ToolSpec(
    name="draw", params=annotate.DrawParams, category="effects",
    run=lambda p, s: annotate.draw(p, s.load(p.image)),
    summary="MS Paint annotations: circles, arrows, lines, rectangles",
    description=("Hand-drawn-looking annotations in the MS Paint tradition: circle=[x,y,r], arrow and line "
                 "=[x1,y1,x2,y2] (arrowhead at the end), rect=[x1,y1,x2,y2]; each is a list, so give as many "
                 "as you like. Red by default: 'circled in red' is the joke format."),
))
register(ToolSpec(
    name="censor", params=annotate.CensorParams, category="effects",
    run=lambda p, s: annotate.censor(p, s.load(p.image)),
    summary="pixelate, black-bar or blur rectangles",
    description=("Censor rectangles: style pixelate (default), bar (solid black, the classic eye bar: use a "
                 "box around find's eye points), or blur. block sets pixel size or blur radius."),
))
register(ToolSpec(
    name="eyes", params=annotate.EyesParams, category="effects",
    run=lambda p, s: annotate.eyes(p, s.load(p.image)),
    summary="laser eyes",
    description=("Laser beams with glow from each point in `at` (use find's eye points on the current "
                 "image: run find again after pasting a new head). angle is the beam direction in degrees "
                 "(0 = right, 90 = up, default 155 = up-left)."),
))
register(ToolSpec(
    name="filter", params=filters.FilterParams, category="effects",
    run=lambda p, s: filters.apply_filters(p, s.load(p.image)),
    summary="emboss, edges, solarize, posterize, sepia and other filters, in order",
    description=("The 'found the Filters menu' look: apply named filters in order (emboss, edges, contour, "
                 "solarize, posterize, invert, grayscale, sepia, blur, sharpen, oilpaint)."),
))
register(ToolSpec(
    name="warp", params=filters.WarpParams, category="effects",
    run=lambda p, s: filters.warp(p, s.load(p.image)),
    summary="bulge or pinch circular spots (giant eyes, huge nose)",
    description=("Bulge (strength > 0) or pinch (strength < 0) circles with blocky pixels. Giant eyes: a spot "
                 "on each find eye point with radius about 0.4x the eye distance. Huge nose: the nose point. "
                 "Default strength 0.6; 1.0 is enormous."),
))
```

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_annotate_filters.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/src/badshop/engine/annotate.py core/src/badshop/engine/filters.py core/src/badshop/tools/catalog.py core/tests/test_annotate_filters.py
git commit -m "feat(engine): draw, censor, laser eyes, filters and warp

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Garnish (flare, sparkle, watermark)

**Files:**
- Create: `core/src/badshop/engine/garnish.py`, `core/tests/test_garnish.py`
- Modify: `core/src/badshop/tools/catalog.py`

**Interfaces:**
- Consumes: `common.rgb`, `common.to_rgb`, `common.clamp_box`, `text.load_font`.
- Produces: `FlareParams`/`flare`, `SparkleParams`/`sparkle`, `WATERMARKS`, `WatermarkParams`/`watermark`; output key `result`, hint `result.png`.

- [ ] **Step 1: Write the failing tests**

`core/tests/test_garnish.py`:
```python
import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from memstore import MemoryStore

CASES = [
    ["flare", "lincoln.png", "--at", "480", "90"],
    ["flare", "lincoln.png", "--at", "100", "500", "--size", "40"],
    ["sparkle", "lincoln.png", "--repeat", "8", "--region", "20", "300", "400", "580", "--seed", "3"],
    ["sparkle", "lincoln.png", "--at", "100", "100", "--at", "200", "150", "--size", "30", "--color", "#88f"],
    ["watermark", "lincoln.png", "hypercam", "bandicam"],
    ["watermark", "lincoln.png", "ifunny", "mematic", "--text", "made in badshop", "--corner", "tl"],
]


@pytest.mark.parametrize("args", CASES, ids=lambda a: " ".join(a[:3]))
def test_parity(pair, args):
    assert pair.new(*args).stdout == pair.ref(*args).stdout
    pair.assert_same("badshop_work/result.png")


def test_ifunny_adds_a_bar():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (400, 300), "white"), "x.png")
    run = run_tool("watermark", {"image": ref, "names": ["ifunny"]}, store)
    w, h = store.images[run.refs[0]].size
    assert w == 400 and h > 300


def test_sparkle_and_watermark_need_something():
    store = MemoryStore()
    ref = store.add(Image.new("RGB", (40, 40)), "x.png")
    with pytest.raises(EngineError):
        run_tool("sparkle", {"image": ref}, store)
    with pytest.raises(EngineError):
        run_tool("watermark", {"image": ref}, store)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_garnish.py -q`
Expected: FAIL (`invalid choice`).

- [ ] **Step 3: Port the module**

`core/src/badshop/engine/garnish.py`: port `cmd_flare` (1049–1078), `cmd_sparkle` (1080–1107), `WATERMARKS` and `cmd_watermark` (1109–1159):
```python
class FlareParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to add a lens flare to")
    at: Point = Field(description="where the light is")
    size: int | None = Field(None, ge=2, description="glow radius in px (default: a sixth of the short side)")


class SparkleParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to sparkle")
    at: list[Point] = Field(default_factory=list, description="sparkle positions; repeatable")
    repeat: int | None = Field(None, ge=1, description="scatter this many at random (as well as any `at`)")
    region: Box | None = Field(None, description="with repeat, only scatter inside this box")
    size: int | None = Field(None, ge=2, description="sparkle radius in px (default: scaled to the image)")
    color: Color = Field("#fff27a", description="glow color")
    seed: int = Field(1, description="change for a different scatter")


WATERMARKS = ("hypercam", "bandicam", "ifunny", "mematic")


class WatermarkParams(Params):
    POSITIONAL: ClassVar = ("image", "names")
    image: ImageRef = Field(description="image to watermark")
    names: list[Literal["hypercam", "bandicam", "ifunny", "mematic"]] = Field(
        default_factory=list, description="fake watermarks to add")
    text: str | None = Field(None, description="your own watermark text as well")
    corner: Literal["tl", "tr", "bl", "br"] = Field("br", description="corner for text")
```
Bodies verbatim with `a.` → `p.`, starting from `to_rgb(image)` (sparkle and watermark then `.convert("RGBA")`), and with these error replacements:
- sparkle: `sys.exit(...)` → `raise EngineError("give at or repeat", hint="at places sparkles, repeat scatters them")`
- watermark: `sys.exit(...)` → `raise EngineError("name a watermark or give text", hint=f"watermarks: {', '.join(WATERMARKS)}")`

Lines:
- flare: `[f"lens flare at ({x}, {y}), size {R}px"]`
- sparkle: `[f"{len(spots)} sparkle(s), size about {size}px"]`
- watermark: `[f"watermarks: {', '.join(marks)}"]`

Register (import `garnish`):
```python
register(ToolSpec(
    name="flare", params=garnish.FlareParams, category="effects",
    run=lambda p, s: garnish.flare(p, s.load(p.image)),
    summary="2004 lens flare",
    description="A cheesy lens flare: glow, streak, and coloured ghost rings marching through the image center.",
))
register(ToolSpec(
    name="sparkle", params=garnish.SparkleParams, category="effects",
    run=lambda p, s: garnish.sparkle(p, s.load(p.image)),
    summary="clip-art four-point sparkles",
    description="Clip-art sparkles with a soft glow, at given points and/or scattered at random (repeat, region).",
))
register(ToolSpec(
    name="watermark", params=garnish.WatermarkParams, category="effects",
    run=lambda p, s: garnish.watermark(p, s.load(p.image)),
    summary="fake HyperCam, Bandicam, iFunny or Mematic watermarks",
    description=("Period-accurate fake watermarks, any combination: hypercam ('Unregistered HyperCam 2', "
                 "top-left), bandicam (top center), ifunny (adds a dark bar under the picture), mematic "
                 "(bottom center). text adds your own in a corner."),
))
```

- [ ] **Step 4: Run the tests**

Run: `cd core && uv run pytest tests/test_garnish.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/badshop/engine/garnish.py core/src/badshop/tools/catalog.py core/tests/test_garnish.py
git commit -m "feat(engine): lens flare, sparkles and fake watermarks

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Finishing (save, deepfry, animate)

**Files:**
- Create: `core/src/badshop/engine/finish.py`, `core/tests/test_finish.py`
- Modify: `core/src/badshop/tools/catalog.py`

**Interfaces:**
- Consumes: `common.jpeg_cycle`, `common.to_rgb`, `Output` (JPEG/GIF encoding).
- Produces: `SaveParams`/`save` (key `saved`), `DeepfryParams`/`deepfry_tool` (key `deepfried`), `deepfry(im, level, tint=True, seed=1) -> tuple[Image, int]`, `AnimateParams`/`animate(p, images: list[Image])` (key `animated`). Name hints: `final:<name>` if `name` is given, else `final:{stem}` (save), `final:{stem}_deepfried` (deepfry), `final:{stem}_<effect>` (animate).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_finish.py`:
```python
import pytest
from PIL import Image

from badshop.engine.finish import deepfry
from conftest import FIXTURES

SAVES = [
    ["--quality", "20", "--passes", "3", "--name", "s"],
    ["--lowres", "0.3", "--name", "s"],
    ["--gif", "--colors", "32", "--name", "s"],
]


@pytest.mark.parametrize("args", SAVES)
def test_save_parity(pair, args):
    assert pair.new("save", "lincoln.png", *args).stdout.replace(str(pair.new_dir), "") == \
        pair.ref("save", "lincoln.png", *args).stdout.replace(str(pair.ref_dir), "")
    ext = ".gif" if "--gif" in args else ".jpg"
    pair.assert_same(f"final/s{ext}")


ANIMS = [
    ["--effect", "none"],
    ["--effect", "shake", "--frames", "6", "--seed", "2"],
    ["--effect", "flash"],
    ["--effect", "zoom", "--at", "300", "250", "--amount", "2.5", "--hold", "2"],
    ["--effect", "spin", "--frames", "5", "--delay", "50"],
]


@pytest.mark.parametrize("args", ANIMS, ids=lambda a: a[1])
def test_animate_parity(pair, args):
    for side in (pair.ref, pair.new):
        side("animate", "lincoln.png", "trump.png", *args, "--name", "a")
    pair.assert_same("final/a.gif")


def test_final_names_never_overwrite(pair):
    pair.new("deepfry", "lincoln.png", "--name", "meme")
    pair.new("deepfry", "lincoln.png", "--name", "meme")
    assert (pair.new_dir / "final/meme.jpg").exists() and (pair.new_dir / "final/meme_2.jpg").exists()


def test_deepfry_is_deterministic_per_seed():
    im = Image.open(FIXTURES / "lincoln.png").convert("RGB")
    a, qa = deepfry(im, 4, seed=7)
    b, _ = deepfry(im, 4, seed=7)
    c, _ = deepfry(im, 4, seed=8)
    assert a.tobytes() == b.tobytes() and a.tobytes() != c.tobytes()
    assert qa == round(22 + (4 - 22) * 0.75)


def test_deepfry_level_increases_saturation():
    im = Image.open(FIXTURES / "trump.png").convert("RGB")
    low, _ = deepfry(im, 1)
    high, _ = deepfry(im, 5)
    sat = lambda x: sum(x.convert("HSV").getchannel("S").getdata()) / (x.width * x.height)  # noqa: E731
    assert sat(high) > sat(low)


def test_animate_fry_runs(pair):
    out = pair.new("animate", "lincoln.png", "--effect", "zoom", "--fry", "5", "--name", "z").stdout
    assert "fried to level 5" in out and Image.open(pair.new_dir / "final/z.gif").n_frames > 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_finish.py -q`
Expected: FAIL (`invalid choice`).

- [ ] **Step 3: Port the module**

`core/src/badshop/engine/finish.py`: port `cmd_save` (1193–1211), `deepfry` (1213–1246), `cmd_deepfry` (1248–1255), `cmd_animate` (1257–1293).

Params:
```python
class SaveParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="finished image")
    quality: int = Field(35, ge=1, le=95, description="JPEG quality")
    passes: int = Field(1, ge=1, le=20, description="recompress this many times for more artifacts")
    lowres: float | None = Field(None, gt=0, le=1, description="downscale to this fraction and back up (0.3 = potato)")
    gif: bool = Field(False, description="write a dithered 1999-style GIF instead of a JPEG")
    colors: int = Field(64, ge=2, le=256, description="with gif, palette size")
    name: str | None = Field(None, description="file name without extension")


class DeepfryParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="image to deep-fry")
    level: int = Field(3, ge=1, le=5, description="1 = lightly toasted, 3 = default, 5 = nuked")
    no_tint: bool = Field(False, description="skip the red/yellow color cast")
    seed: int = Field(1, description="grain pattern; same seed, same result")
    name: str | None = Field(None, description="file name without extension")


class AnimateParams(Params):
    POSITIONAL: ClassVar = ("images",)
    images: list[ImageRef] = Field(min_length=1, description="frames cycle through these (e.g. with and without laser eyes)")
    effect: Literal["none", "shake", "flash", "zoom", "spin"] = Field("none", description="motion effect")
    frames: int | None = Field(None, ge=1, le=120, description="frame count (default depends on the effect)")
    delay: int = Field(80, ge=10, description="ms per frame")
    amount: float | None = Field(None, gt=0, description="shake: max px offset; zoom: final zoom factor (default 3)")
    at: Point | None = Field(None, description="zoom target (default: the center)")
    hold: int = Field(6, ge=0, description="zoom: repeat the last frame this many times")
    fry: int | None = Field(None, ge=1, le=5, description="deep-fry every frame at this level (zoom ramps up to it)")
    colors: int = Field(128, ge=2, le=256, description="palette size per frame")
    seed: int = Field(1, description="shake pattern")
    name: str | None = Field(None, description="file name without extension")
```

The one intended pixel change: `deepfry` gains `seed` and replaces the reference's unseeded grain line (`noise = Image.effect_noise(im.size, lerp(6, 34)).convert("RGB")`) with:
```python
    import numpy as np
    w, h = im.size
    rng = np.random.default_rng(seed)
    grain = rng.normal(128.0, lerp(6, 34), size=(h, w)).clip(0, 255).astype(np.uint8)
    noise = Image.fromarray(grain, "L").convert("RGB")  # same gaussian grain, now reproducible
```
Everything else in `deepfry` is verbatim. `animate` passes its `seed` into the per-frame `deepfry` calls.

Function bodies (verbatim with `a.` → `p.`; images come in as arguments):
```python
def save(p: SaveParams, image: Image.Image) -> EngineResult:
    im = to_rgb(image)
    # ...reference lowres + passes lines verbatim...
    hint = f"final:{p.name}" if p.name else "final:{stem}"
    if p.gif:
        out = Output("saved", im.quantize(colors=p.colors, dither=Image.Dither.FLOYDSTEINBERG), hint, fmt="GIF")
        return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}, gif with {p.colors} colors, dithered"])
    out = Output("saved", im, hint, fmt="JPEG", quality=p.quality)
    return EngineResult(outputs=[out], lines=[f"size: {im.width}x{im.height}, jpeg quality {p.quality}, {p.passes} pass(es)"])


def deepfry_tool(p: DeepfryParams, image: Image.Image) -> EngineResult:
    im, quality = deepfry(to_rgb(image), p.level, tint=not p.no_tint, seed=p.seed)
    hint = f"final:{p.name}" if p.name else "final:{stem}_deepfried"
    return EngineResult(outputs=[Output("deepfried", im, hint, fmt="JPEG", quality=quality)],
                        lines=[f"size: {im.width}x{im.height}, level {p.level}"])


def animate(p: AnimateParams, images: list[Image.Image]) -> EngineResult:
    sources = [to_rgb(i) for i in images]
    # ...reference lines 1259-1288 verbatim with `a.` -> `p.` (frames list built the same way)...
    hint = f"final:{p.name}" if p.name else f"final:{{stem}}_{p.effect}"
    out = Output("animated", frames[0], hint, fmt="GIF", frames=frames, duration=p.delay)
    return EngineResult(outputs=[out], lines=[f"size: {W}x{H}, {len(frames)} frames at {p.delay}ms, effect {p.effect}"
                                              + (f", fried to level {p.fry}" if p.fry else "")])
```

Register (import `finish`):
```python
register(ToolSpec(
    name="save", params=finish.SaveParams, category="finish",
    run=lambda p, s: finish.save(p, s.load(p.image)),
    summary="write a crunchy low-quality JPEG, or a dithered GIF",
    description=("Finish as a low-quality JPEG (quality, passes to recompress, lowres for potato quality) or a "
                 "dithered GIF. Saved to the user's output folder; give a descriptive name."),
))
register(ToolSpec(
    name="deepfry", params=finish.DeepfryParams, category="finish",
    run=lambda p, s: finish.deepfry_tool(p, s.load(p.image)),
    summary="deep-fried meme treatment, written as a JPEG",
    description=("Deep-fry: red/yellow cast, blown-out saturation and contrast, oversharpened halos, grain, "
                 "rounds of low-quality JPEG. level 1-5 from how strongly the user put it (fried=3, "
                 "nuked=5). Replaces save. Give a descriptive name."),
))
register(ToolSpec(
    name="animate", params=finish.AnimateParams, category="finish",
    run=lambda p, s: finish.animate(p, [s.load(r) for r in p.images]),
    summary="animated GIF: flip between images, shake, flash, zoom, spin",
    description=("Make an animated GIF. Several images alternate (e.g. with and without lasers for flashing "
                 "laser eyes). effect shake/flash/zoom/spin; zoom with at=[x,y] and fry=5 is the classic "
                 "zoom-and-deep-fry. Give a descriptive name."),
))
```

- [ ] **Step 4: Run the tests**

Run: `cd core && uv run pytest tests/test_finish.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/badshop/engine/finish.py core/src/badshop/tools/catalog.py core/tests/test_finish.py
git commit -m "feat(engine): save, seeded deepfry and animated GIFs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Image sources (fetch, wiki, emoji, template, clipboard)

**Files:**
- Create: `core/src/badshop/engine/sources.py`, `core/tests/fixtures/api/` (recorded responses), `core/tests/test_sources.py`
- Modify: `core/tests/fixtures/make_fixtures.py` (add API recording), `core/src/badshop/tools/catalog.py`

**Interfaces:**
- Consumes: `assets.http_get`, `common.has_alpha`, `common.load_image`.
- Produces: `FetchParams`/`fetch`, `WikiParams`/`wiki`, `EmojiParams`/`emoji`, `TemplateParams`/`template`, `emoji_code(s) -> str`, `EMOJI_NAMES`. Candidate outputs have keys `"1"`, `"2"`, …, hints `fetch/<slug>_<n><ext>`, and captions `(WxH) title  [note]`; a `sheet` output (hint `fetch/<slug>_sheet.png`) when there is more than one candidate. URL and clipboard modes produce one `fetched` output (hint `fetch/<slug>.png` or `fetch/clipboard_<HHMMSS>.png`). Emoji outputs have key `emoji`, hint `fetch/emoji_<code>.png`, and stay RGBA.

- [ ] **Step 1: Record the API fixtures (one-time, needs internet)**

Add to `make_fixtures.py` a `record_api()` function, called from `main()`, that saves these responses under `core/tests/fixtures/api/`:
```python
API = {
    "commons.json": "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": "golden retriever filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 1200}),
    "openverse.json": "https://api.openverse.org/v1/images/?q=golden+retriever&page_size=8&mature=false",
    "wiki.json": "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": "Abraham Lincoln",
        "gsrnamespace": 0, "gsrlimit": 6, "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": 1200, "pilimit": "max"}),
    "imgflip.json": "https://api.imgflip.com/get_memes",
}


def record_api() -> None:
    d = HERE / "api"
    d.mkdir(exist_ok=True)
    for name, url in API.items():
        (d / name).write_bytes(get(url))
        print("api/" + name)
    (d / "page.html").write_text(
        '<html><head><meta property="og:image" content="/images/lincoln.png"></head><body>hi</body></html>')
```
Run: `cd core && uv run python tests/fixtures/make_fixtures.py`
Expected: prints the four `api/*.json` names; `page.html` written.

- [ ] **Step 2: Write the failing tests**

`core/tests/test_sources.py`:
```python
import json
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

from badshop.engine import sources
from badshop.engine.errors import EngineError
from badshop.tools.runner import run_tool
from conftest import FIXTURES
from memstore import MemoryStore

API = FIXTURES / "api"


def fake_http(requested: list[str]):
    """Serve recorded API JSON by host, the page fixture for .html, and a fixture image for anything else."""
    def get(url: str, timeout: float = 30):
        requested.append(url)
        if "commons.wikimedia.org/w/api.php" in url:
            return (API / "commons.json").read_bytes(), "application/json"
        if "api.openverse.org" in url:
            return (API / "openverse.json").read_bytes(), "application/json"
        if "wikipedia.org/w/api.php" in url:
            return (API / "wiki.json").read_bytes(), "application/json"
        if "api.imgflip.com" in url:
            return (API / "imgflip.json").read_bytes(), "application/json"
        if url.endswith(".html"):
            return (API / "page.html").read_bytes(), "text/html"
        if "twemoji" in url:
            return (FIXTURES / "emoji_joy.png").read_bytes(), "image/png"
        return (FIXTURES / "lincoln.png").read_bytes(), "image/png"
    return get


@pytest.fixture
def web(monkeypatch):
    requested: list[str] = []
    monkeypatch.setattr(sources, "http_get", fake_http(requested))
    return requested


def test_fetch_interleaves_and_dedupes(web):
    store = MemoryStore()
    run = run_tool("fetch", {"query": "golden retriever", "n": 4}, store)
    keys = [o.key for o in run.result.outputs]
    assert keys == ["1", "2", "3", "4", "sheet"]
    notes = [o.caption for o in run.result.outputs[:4]]
    assert "[commons]" in notes[0] and "[openverse" in notes[1]
    assert run.result.outputs[0].name_hint.startswith("fetch/golden_retriever_1")


def test_fetch_page_url_follows_og_image(web):
    store = MemoryStore()
    run = run_tool("fetch", {"query": "https://example.org/article.html"}, store)
    assert run.result.outputs[0].key == "fetched"
    assert any(u == "https://example.org/images/lincoln.png" for u in web)


def test_wiki_requests_all_page_images(web):
    run = run_tool("wiki", {"title": "Abraham Lincoln", "n": 2}, MemoryStore())
    assert "pilimit=max" in web[0]
    assert run.result.outputs[0].caption.endswith("Abraham Lincoln  [wikipedia lead image]")


@pytest.mark.parametrize("given,code", [("😂", "1f602"), ("🅱️", "1f171"), ("🇺🇸", "1f1fa-1f1f8"),
                                        ("skull", "1f480"), (":joy:", "1f602"), ("1f525", "1f525"),
                                        ("👨‍💻", "1f468-200d-1f4bb")])
def test_emoji_code(given, code):
    assert sources.emoji_code(given) == code


def test_emoji_keeps_transparency(web):
    store = MemoryStore()
    run = run_tool("emoji", {"emoji": ["😂"], "size": 144}, store)
    im = store.images[run.refs[0]]
    assert im.mode == "RGBA" and im.size == (144, 144) and im.getpixel((0, 0))[3] == 0


def test_template_fuzzy_match(web):
    run = run_tool("template", {"name": "distracted", "n": 1}, MemoryStore())
    assert "Distracted Boyfriend" in run.result.outputs[0].caption


def test_template_list(web):
    run = run_tool("template", {"list_all": True}, MemoryStore())
    assert run.refs == [] and any("Drake" in l for l in run.result.lines)


def test_fetch_offline(monkeypatch):
    def down(url, timeout=30):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(sources, "http_get", down)
    with pytest.raises(EngineError) as e:
        run_tool("fetch", {"query": "golden retriever"}, MemoryStore())
    assert e.value.hint and "internet" in e.value.hint


def test_clipboard_link(monkeypatch, web):
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "https://example.org/pic.png"))
    run = run_tool("fetch", {"clipboard": True}, MemoryStore())
    assert run.result.outputs[0].key == "fetched" and web[-1] == "https://example.org/pic.png"


def test_clipboard_empty(monkeypatch):
    monkeypatch.setattr(sources, "read_clipboard", lambda: (None, "just some words"))
    with pytest.raises(EngineError):
        run_tool("fetch", {"clipboard": True}, MemoryStore())


@pytest.mark.network
def test_live_wiki(pair):
    out = pair.new("wiki", "Abraham Lincoln", "-n", "1").stdout
    assert out.startswith("1: badshop_work/fetch/wiki_abraham_lincoln_1")
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_sources.py -q`
Expected: collection error (`cannot import name 'sources'`).

- [ ] **Step 4: Port the module**

`core/src/badshop/engine/sources.py`: port reference lines 304–627. Rules:
- Import `http_get` into the module namespace (`from badshop.engine.assets import http_get`) and always call it as a module global, so the tests' monkeypatch works.
- `try_image` returns `load_image(data)` or `None` on any exception.
- `save_fetched` is gone: outputs keep the image with `im.convert("RGBA") if has_alpha(im) else im.convert("RGB")`, and `fmt` is `FORMAT_EXT` → the format name (`"JPEG"`, `"PNG"`, `"GIF"`, `"WEBP"`, default `"PNG"`).
- `download_candidates(hits, slug, source_line)` returns an `EngineResult`. Each candidate becomes `Output(str(i), im, f"fetch/{slug}_{i}{ext}", fmt=fmt, caption=f"({im.width}x{im.height}) {title}{note}")`, where `note = f"  [{h['note']}]"` when present. Per-candidate failures and the `source_line` go into `lines` in the reference's order. The sheet is `Output("sheet", sheet, f"fetch/{slug}_sheet.png")` when there are 2+ panels. With no panels, `raise EngineError("every candidate failed to download", hint="try other words or another source")`.
- **Network failures:** wrap every search call so `urllib.error.URLError`, `TimeoutError` and `OSError` become `EngineError(f"{source} search failed ({e})", hint="check the internet connection, or use a local file")`. In `fetch`'s multi-source mode, a failing source adds a `note: <name> search failed (…)` line as today, and only if *all* sources fail does it raise that `EngineError`.
- `fetch_url(url)` returns `EngineResult(outputs=[Output("fetched", im, "fetch/" + slugify(Path(urlparse(url).path).stem) + ".png")], lines=[f"size: {w}x{h}"])` plus a `page image: <url>` line first when it followed `og:image`. Its `sys.exit`s become `EngineError`s with the same messages; the "no og:image" one gets `hint="right-click the picture and copy the image address instead"`.
- `read_clipboard()` is verbatim, but the "no clipboard tool" `sys.exit` → `EngineError(..., hint="install wl-clipboard (Wayland), xclip (X11), or pngpaste (macOS)")`. `fetch_clipboard()` returns an `Output("fetched", im, f"fetch/clipboard_{time.strftime('%H%M%S')}.png")`, or follows a URL through `fetch_url`, or raises `EngineError("the clipboard has no image or link", hint="copy an image (or its address) and try again")`.
- Params:
  ```python
  class FetchParams(Params):
      POSITIONAL: ClassVar = ("query",)
      FLAGS: ClassVar = {"n": "-n"}
      query: str | None = Field(None, description='search words like "labrador retriever sitting", or an image or web page URL')
      source: Literal["all", "commons", "openverse"] = Field("all", description="where to search (all interleaves Commons and Openverse)")
      n: int = Field(6, ge=1, le=12, description="how many candidates to download")
      clipboard: bool = Field(False, description="use the image (or image link) on the clipboard")


  class WikiParams(Params):
      POSITIONAL: ClassVar = ("title",)
      FLAGS: ClassVar = {"n": "-n"}
      title: str = Field(description='a person, place or thing, e.g. "Abraham Lincoln"')
      n: int = Field(4, ge=1, le=8, description="how many matching articles (the first is usually the exact one)")
      lang: str = Field("en", pattern=r"^[a-z-]{2,12}$", description="Wikipedia language code")


  class EmojiParams(Params):
      POSITIONAL: ClassVar = ("emoji",)
      emoji: list[str] = Field(min_length=1, description="emoji characters, hex codes (1f480) or names (skull, joy, fire...)")
      size: int | None = Field(None, ge=8, le=1024, description="nearest-neighbor upscale to this many px")


  class TemplateParams(Params):
      POSITIONAL: ClassVar = ("name",)
      FLAGS: ClassVar = {"n": "-n", "list_all": "--list"}
      name: str | None = Field(None, description='template name, e.g. "drake", "distracted boyfriend"')
      n: int = Field(3, ge=1, le=8, description="how many best matches to download")
      list_all: bool = Field(False, description="list every template name instead")
  ```
- `fetch(p)`: `if p.clipboard: return fetch_clipboard()`; `if not p.query: raise EngineError("give search words, an image or page URL, or clipboard")`; URL → `fetch_url`; else the interleaving search as in `cmd_fetch`.
- `template(p)` with `list_all` (or no name) returns only `lines` (one per template, the reference's format).
- `emoji(p)` lines: the reference's `emoji: {out}…` print becomes the output (key `emoji`, caption `f"({w}x{h}) {character}"`); the final `source:` line goes into `lines`; unknown names add the reference's "no Twemoji image…" line; no downloads at all → `EngineError("no emoji downloaded", hint=...)`.

Register (import `sources`), all with `network=True`:
```python
register(ToolSpec(
    name="fetch", params=sources.FetchParams, category="sources", network=True,
    run=lambda p, s: sources.fetch(p),
    summary="search Commons + Openverse, download an image or page URL, or grab the clipboard",
    description=("Get images. Search words are a keyword search: use a short literal description of the "
                 "picture ('labrador retriever sitting', not 'dog for meme'). Returns numbered candidates and "
                 "a contact sheet: look at the sheet and pick the one with the part you need at a usable "
                 "angle. query may also be an image URL or a web page URL (its preview image is used). "
                 "clipboard=true takes what the user copied. For a named person or thing prefer wiki."),
))
register(ToolSpec(
    name="wiki", params=sources.WikiParams, category="sources", network=True,
    run=lambda p, s: sources.wiki(p),
    summary="lead images of Wikipedia articles matching a name",
    description=("The lead image of the best-matching Wikipedia articles. The best first try for any named "
                 "person, place, building, animal breed or artwork; candidate 1 is almost always the exact "
                 "article."),
))
register(ToolSpec(
    name="emoji", params=sources.EmojiParams, category="sources", network=True,
    run=lambda p, s: sources.emoji(p),
    summary="transparent Twemoji PNGs by character, hex code or name",
    description=("Transparent 72px emoji images (Twemoji). Give characters (😂), hex codes (1f480) or names "
                 "(joy, rofl, sob, skull, fire, 100, eyes, ok, b, clown, moyai, flag_us, stonks...). Always "
                 "use this for emoji, never a search. Paste with repeat for emoji rain."),
))
register(ToolSpec(
    name="template", params=sources.TemplateParams, category="sources", network=True,
    run=lambda p, s: sources.template(p),
    summary="classic meme templates from Imgflip by name",
    description=("Classic meme templates by name from Imgflip's top 100 (drake, distracted boyfriend, two "
                 "buttons, change my mind...). Returns the best matches; list_all=true lists them all."),
))
```

- [ ] **Step 5: Run the tests**

Run: `cd core && uv run pytest tests/test_sources.py -v`
Expected: all PASS except `test_live_wiki` (deselected by the default `-m 'not network'`). Then run `cd core && uv run pytest tests/test_sources.py -m network -v` once with internet: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/src/badshop/engine/sources.py core/src/badshop/tools/catalog.py core/tests/test_sources.py core/tests/fixtures
git commit -m "feat(engine): image sources (Commons, Openverse, Wikipedia, Twemoji, Imgflip, clipboard)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Export tool, recipes, and full catalog parity

**Files:**
- Create: `core/src/badshop/cli/recipes.py`, `core/tests/test_recipes.py`, `core/tests/test_catalog_parity.py`
- Modify: `core/src/badshop/cli/main.py` (add recipe/run commands and history recording), `core/src/badshop/tools/catalog.py` (register `export`), `core/src/badshop/engine/basic.py` (add `ExportParams`)

**Interfaces:**
- Consumes: everything above; `FileStore.export`.
- Produces: tool `export`; CLI commands `recipe` and `run` with the reference's flags; `recipes.record(argv: list[str]) -> None`, `recipes.RECIPE_COMMANDS = {"recipe", "run"}`, `recipes.add_parsers(sub)`, `recipes.run_command(a, main) -> int`. History lives in `badshop_work/history.jsonl` (the reference's format: `{"argv": [...], "time": "..."}` per line).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_catalog_parity.py`:
```python
"""Every reference command and flag must exist in the new CLI."""

import argparse
import importlib.util

import pytest

from badshop.cli.main import build_parser
from badshop.tools import REGISTRY
from badshop.tools.registry import image_fields
from conftest import REFERENCE


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


@pytest.fixture(scope="module")
def reference_parser() -> argparse.ArgumentParser:
    spec = importlib.util.spec_from_file_location("reference_badshop", REFERENCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    captured = {}
    original = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        captured["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = grab
    try:
        mod.main(["info", "x"])
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    return captured["p"]


def test_every_reference_command_exists(reference_parser):
    new = _subparsers(build_parser())
    assert set(_subparsers(reference_parser)) <= set(new)


def test_every_reference_flag_and_positional_exists(reference_parser):
    new = _subparsers(build_parser())
    for name, ref_sub in _subparsers(reference_parser).items():
        ref_opts = {o for a in ref_sub._actions for o in a.option_strings}
        new_opts = {o for a in new[name]._actions for o in a.option_strings}
        assert ref_opts <= new_opts, f"{name}: missing {ref_opts - new_opts}"
        ref_pos = [a.dest for a in ref_sub._actions if not a.option_strings]
        new_pos = [a.dest for a in new[name]._actions if not a.option_strings]
        assert ref_pos == new_pos, f"{name}: positionals {new_pos} != {ref_pos}"


def test_registry_is_complete_and_described():
    engine_tools = {"prep", "fetch", "wiki", "emoji", "template", "find", "cutout", "paste", "text", "draw",
                    "censor", "eyes", "warp", "flare", "sparkle", "watermark", "filter", "save", "deepfry",
                    "animate", "info"}
    assert set(REGISTRY) == engine_tools | {"view", "export"}
    for spec in REGISTRY.values():
        assert len(spec.description) >= 40, spec.name
        spec.params.model_json_schema()  # must not raise
        for field in image_fields(spec.params):
            assert field in spec.params.model_fields
```

`core/tests/test_recipes.py`:
```python
import json


def test_recipe_collapses_reruns_and_replays(pair):
    pair.new("recipe", "--clear")
    pair.new("text", "lincoln.png", "first try", "-o", "badshop_work/a.png")
    pair.new("text", "lincoln.png", "second try", "-o", "badshop_work/a.png")
    pair.new("eyes", "badshop_work/a.png", "--at", "260", "240", "-o", "badshop_work/b.png")
    pair.new("info", "badshop_work/b.png")  # read-only: not recorded
    out = pair.new("recipe").stdout
    assert "2 step(s) from 3 logged command(s)" in out
    recipe = json.loads((pair.new_dir / "badshop_work/recipe.json").read_text())
    assert recipe["steps"][0][2] == "second try"

    recipe["steps"][0][2] = "{caption}"
    (pair.new_dir / "badshop_work/recipe.json").write_text(json.dumps(recipe))
    out = pair.new("run", "badshop_work/recipe.json", "--set", "caption=PROBLEM, LIBURALS??").stdout
    assert "== step 1/2: text lincoln.png 'PROBLEM, LIBURALS??'" in out
    assert "== step 2/2: eyes" in out


def test_run_from_skips_earlier_steps(pair):
    pair.new("recipe", "--clear")
    pair.new("text", "lincoln.png", "x", "-o", "badshop_work/a.png")
    pair.new("eyes", "badshop_work/a.png", "--at", "10", "10", "-o", "badshop_work/b.png")
    pair.new("recipe")
    out = pair.new("run", "badshop_work/recipe.json", "--from", "2").stdout
    assert "step 1/2" not in out and "step 2/2" in out


def test_run_stops_on_failure(pair):
    (pair.new_dir / "bad.json").write_text(json.dumps({"vars": {}, "steps": [["info", "nope.png"], ["info", "lincoln.png"]]}))
    p = pair.new("run", "bad.json", check=False)
    assert p.returncode == 1 and "step 1 failed" in p.stderr and "step 2/2" not in p.stdout


def test_export_copies_without_overwriting(pair):
    pair.new("export", "lincoln.png", "--name", "keep")
    pair.new("export", "lincoln.png", "--name", "keep")
    assert (pair.new_dir / "final/keep.png").exists() and (pair.new_dir / "final/keep_2.png").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && uv run pytest tests/test_recipes.py tests/test_catalog_parity.py -q`
Expected: FAIL (`invalid choice: 'recipe'`, `'export'`; the registry is missing `export`).

- [ ] **Step 3: Add the export tool**

Append to `core/src/badshop/engine/basic.py`:
```python
class ExportParams(Params):
    POSITIONAL: ClassVar = ("image",)
    image: ImageRef = Field(description="finished image to hand to the user")
    name: str | None = Field(None, description="file name without extension")
```
Register in `catalog.py`:
```python
register(ToolSpec(
    name="export", params=basic.ExportParams, category="finish", mutates=False,
    run=lambda p, s: EngineResult(lines=[f"exported: {s.export(p.image, p.name)}"]),
    summary="copy a finished image into the output folder",
    description=("Copy a finished image, unchanged (animation included), into the user's output folder "
                 "under a descriptive name, never overwriting. save and deepfry already do this; use export "
                 "for anything else the user wants to keep."),
))
```
(Add `from badshop.engine.result import EngineResult` to the catalog's imports.)

- [ ] **Step 4: Port recipes**

`core/src/badshop/cli/recipes.py`: port reference lines 1300–1372 (`output_of`, `record`, `cmd_recipe`, `cmd_run`) with these changes:
- `HISTORY = Path("badshop_work") / "history.jsonl"`.
- `record(argv)` skips when `argv[0]` is `recipe` or `run`, or when the tool is `read_only` or `network` (`REGISTRY[argv[0]].read_only or .network`), or while `REPLAYING` is true.
- `cmd_recipe(a)` returns `0` and prints exactly as the reference; its `sys.exit` for empty history → `print(..., file=sys.stderr); return 1`.
- `cmd_run(a, main)` sets the module-global `REPLAYING = True` (reset in `finally`), prints `== step {i}/{n}: {shlex.join(argv)}`, calls `rc = main(argv)`, and on `rc != 0` prints `step {i} failed` to stderr and returns `rc`.
- `add_parsers(sub)` adds `recipe` (`--last`, `--clear`, `-o/--out`) and `run` (`recipe` positional, `--set` repeatable, `--from` dest `from_step` default 1) with the reference's help strings, and `set_defaults(_recipe=...)`.
- `RECIPE_COMMANDS = {"recipe", "run"}`.

Modify `main.py`:
```python
from badshop.cli import recipes

def build_parser() -> argparse.ArgumentParser:
    ...
    for spec in REGISTRY.values():
        add_tool_parser(sub, spec)
    recipes.add_parsers(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    if a.cmd in recipes.RECIPE_COMMANDS:
        return recipes.run_command(a, main)
    ...  # unchanged body
    recipes.record(argv)
    return 0
```

- [ ] **Step 5: Run the whole suite**

Run: `cd core && uv run pytest -q && uv run ruff check .`
Expected: every test PASSES (network tests deselected), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add core
git commit -m "feat(cli): export tool, recipes, and reference catalog parity

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Done when

- `cd core && uv run pytest -q` passes (with models downloaded into `core/.test-cache`), and `uv run pytest -m network -q` passes with internet.
- `uv run badshop --help` lists 25 commands: 23 tools (the 21 engine tools plus `view` and `export`) and `recipe` and `run`. Every reference invocation in `reference/SKILL.md` runs unchanged with `uv run badshop` in place of `uv run -q …/badshop.py`.
- `REGISTRY` exposes all 23 tools with LLM descriptions and JSON schemas. That is Plan 2's input.
