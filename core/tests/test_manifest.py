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
