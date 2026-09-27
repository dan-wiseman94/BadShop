"""Shared fixtures. The `pair` fixture runs the reference CLI and the new CLI side by side."""

import importlib.util
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
# In-process tests must never write into the user's real app data dir either.
os.environ.setdefault("BADSHOP_DATA_DIR", str(TEST_CACHE / "data"))
os.environ.setdefault("REMBG_HOME", str(TEST_CACHE / "rembg"))
os.environ.setdefault("U2NET_HOME", str(TEST_CACHE / "rembg"))


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
    p = subprocess.run(cmd, cwd=cwd, env=cli_env(cwd), capture_output=True, text=True, encoding="utf-8",
                       timeout=900)
    if check:
        assert p.returncode == 0, f"{cmd}\n--- stdout\n{p.stdout}\n--- stderr\n{p.stderr}"
    return p


def frames(path: Path) -> tuple[list[bytes], tuple[int, int], list[int | None], int | None]:
    """Each frame's RGBA bytes, the size, each frame's duration, and the loop count."""
    with Image.open(path) as im:
        loop = im.info.get("loop")  # read before seeking: later frames may not carry it
        pixels, durations = [], []
        for f in ImageSequence.Iterator(im):
            pixels.append(f.convert("RGBA").tobytes())
            durations.append(f.info.get("duration"))
        return pixels, im.size, durations, loop


def assert_same_image(a: Path, b: Path) -> None:
    with Image.open(a) as ia, Image.open(b) as ib:
        assert ia.format == ib.format, f"format {ia.format} != {ib.format} ({a} vs {b})"
        assert ia.mode == ib.mode, f"mode {ia.mode} != {ib.mode} ({a} vs {b})"
    fa, sa, da, la = frames(a)
    fb, sb, db, lb = frames(b)
    assert sa == sb, f"size {sa} != {sb} ({a} vs {b})"
    assert len(fa) == len(fb), f"{len(fa)} frames != {len(fb)}"
    for i, (x, y) in enumerate(zip(fa, fb)):
        assert x == y, f"frame {i} pixels differ: {a} vs {b}"
    assert da == db, f"frame durations {da} != {db} ({a} vs {b})"
    assert la == lb, f"loop {la} != {lb} ({a} vs {b})"


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

    def check(self, *args: str, files: tuple[str, ...] | list[str] = ()) -> str:
        """Run one command on both sides. Stdout must match, with each side's folder written as <CWD>,
        and so must every listed file (pixels, frames, durations, loop, format and mode).
        Returns the normalised stdout."""
        ref = self.ref(*args).stdout.replace(str(self.ref_dir), "<CWD>")
        new = self.new(*args).stdout.replace(str(self.new_dir), "<CWD>")
        assert new == ref
        for f in files:
            self.assert_same(f)
        return new


@pytest.fixture
def pair(tmp_path: Path) -> Pair:
    return Pair(tmp_path)


def load_reference():
    """reference/badshop.py as a module, for in-process comparisons (a fresh copy on every call)."""
    spec = importlib.util.spec_from_file_location("reference_badshop", REFERENCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def reference():
    """The reference module, shared. Tests may monkeypatch its globals; monkeypatch restores them."""
    return load_reference()
