import io
import json
import os
import struct
import zipfile

import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine.errors import EngineError
from badshop.engine.layouts import LayoutParams, definitions, render
from badshop.session.library import AssetDetails, AssetLibrary
from badshop.session import packs
from badshop.session.session import Session


@pytest.mark.parametrize("definition", definitions(), ids=lambda d: d["id"])
def test_layout_regions_are_bounded_and_each_slot_accepts_edits(definition):
    width, height = definition["width"], definition["height"]
    assert max(width, height) <= 1000
    for item in definition["slots"]:
        for key in ("box", "caption_box"):
            x1, y1, x2, y2 = item[key]
            assert 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    last = len(definition["slots"]) - 1
    boxes = [s["box"] for s in definition["slots"]]
    boxes[last] = [width // 2 - 10, height // 2 - 10, width // 2 + 10, height // 2 + 10]
    p = LayoutParams(template=definition["id"], images=["last"], image_slots=[last], slots=boxes, fit="stretch")
    result = render(p, [Image.new("RGB", (3, 2), (1, 2, 3))])
    assert result.outputs[0].image.getpixel((width // 2, height // 2)) == (1, 2, 3)
    assert result.data["layout"]["slots"][last]["box"] == boxes[last]


def test_layout_preserves_hard_source_colors_and_binary_alpha():
    image = Image.new("RGBA", (2, 1))
    image.putdata([(231, 22, 44, 127), (0, 170, 251, 128)])
    p = LayoutParams(images=["x"], fit="stretch", slots=[[100, 200, 200, 300]], background="white")
    output = render(p, [image]).outputs[0].image
    assert output.getpixel((110, 250)) == (255, 255, 255)
    assert output.getpixel((190, 250)) == (0, 170, 251)


def test_empty_middle_slots_do_not_shift_images():
    p = LayoutParams(template="comic", images=["x"], image_slots=[1], fit="stretch")
    image = render(p, [Image.new("RGB", (2, 2), "red")]).outputs[0].image
    assert image.getpixel((750, 200)) == (255, 0, 0)
    assert image.getpixel((200, 200)) != (255, 0, 0)


@pytest.mark.parametrize("params", [dict(slots=[[0, 0, 9000, 9000]]), dict(images=["a", "b"]),
                                    dict(images=["a"], image_slots=[2]), dict(template="comic", slots=[[1, 1, 2, 2]])])
def test_invalid_geometry_is_refused(params):
    with pytest.raises(ValidationError):
        LayoutParams(**params)


def test_builtin_packs_have_distinct_hard_alpha_and_anchors(tmp_path):
    library = AssetLibrary(tmp_path)
    hashes = set()
    for item in packs.listing():
        entries = packs.install_builtin(library, item["id"])
        assert len(entries) == item["count"] == 4
        for entry in entries:
            hashes.add(entry["artifact"]["id"])
            assert entry["metadata"]["anchors"]["center"] == [entry['artifact']['width']//2, entry['artifact']['height']//2]
            assert entry["artifact"]["source"]["creator"] == "badshop procedural artwork"
            assert entry["artifact"]["source"]["license"] == "MIT"
            with Image.open(io.BytesIO(library._blob(library.get(entry["id"]).artifact))) as im:
                assert set(im.convert('RGBA').getchannel("A").get_flattened_data()) <= {0, 255}
                for x, y in entry["metadata"]["anchors"].values():
                    assert 0 <= x < im.width and 0 <= y < im.height
    assert len(hashes) == sum(item['count'] for item in packs.listing())


@pytest.mark.parametrize("pack_id", ["local-cable", "bargain-packaging", "office-bureaucracy"])
def test_new_pack_artwork_is_repeatable_and_keeps_credits_when_shared(tmp_path, pack_id):
    library = AssetLibrary(tmp_path / "source")
    first = packs.install_builtin(library, pack_id)
    second = packs.install_builtin(library, pack_id)
    assert [e["artifact"]["id"] for e in first] == [e["artifact"]["id"] for e in second]
    path = tmp_path / f"{pack_id}.badpack"
    packs.export_pack(library, [e["id"] for e in first], str(path), pack_id)
    restored = packs.import_pack(AssetLibrary(tmp_path / "target"), str(path))["entries"]
    assert [(e["artifact"], e["metadata"], e["tags"]) for e in restored] == [
        (e["artifact"], e["metadata"], e["tags"]) for e in first]


def test_pack_roundtrip_preserves_pixels_original_credits_and_anchors(tmp_path):
    library = AssetLibrary(tmp_path / "a")
    entry = packs.install_builtin(library, "homepage-1998")[0]
    path = tmp_path / "pack.badpack"
    packs.export_pack(library, [entry["id"]], str(path), "Homepage")
    second = AssetLibrary(tmp_path / "b")
    result = packs.import_pack(second, str(path))
    restored = result["entries"][0]
    assert restored["id"] != entry["id"]
    assert restored["metadata"] == entry["metadata"]
    assert restored["artifact"] == entry["artifact"]
    assert second._blob(second.get(restored["id"]).artifact) == library._blob(library.get(entry["id"]).artifact)
    session = Session.new()
    assert second.restore(session, restored["id"])["working"]["id"] == entry["artifact"]["id"]
    with pytest.raises(EngineError):
        packs.export_pack(library, [entry["id"]], str(path))


@pytest.mark.parametrize("extra", ["../escape", "/absolute", "images\\escape", "surprise.txt"])
def test_pack_rejects_unsafe_or_unexpected_members(tmp_path, extra):
    library = AssetLibrary(tmp_path / "a")
    entry = packs.install_builtin(library, "school-lab")[0]
    path = tmp_path / "bad.badpack"
    packs.export_pack(library, [entry["id"]], str(path))
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(extra, "bad")
    target = AssetLibrary(tmp_path / "target")
    with pytest.raises(EngineError):
        packs.import_pack(target, str(path))
    assert not target.list()
    assert not (tmp_path / "escape").exists()


def test_pack_rejects_hash_mismatch_without_partial_install(tmp_path):
    library = AssetLibrary(tmp_path / "a")
    entries = packs.install_builtin(library, "school-lab")
    path = tmp_path / "good.badpack"
    packs.export_pack(library, [e["id"] for e in entries], str(path))
    damaged = tmp_path / "bad.badpack"
    with zipfile.ZipFile(path) as original, zipfile.ZipFile(damaged, "w") as bad:
        for index, name in enumerate(original.namelist()):
            bad.writestr(name, b"broken" if index == 2 else original.read(name))
    target = AssetLibrary(tmp_path / "target")
    with pytest.raises(EngineError, match="hash"):
        packs.import_pack(target, str(damaged))
    assert not target.list()


def test_pack_keeps_full_resolution_original(tmp_path):
    source = Session.new()
    data = io.BytesIO()
    Image.new("RGB", (1300, 20), "blue").save(data, "PNG")
    image = source.import_image(data.getvalue(), "wide")
    library = AssetLibrary(tmp_path / "a")
    entry = library.save(source, image.id, "Wide", [], AssetDetails(anchors={"left": (0, 0)}))
    path = tmp_path / "original.badpack"
    packs.export_pack(library, [entry["id"]], str(path))
    result = packs.import_pack(AssetLibrary(tmp_path / "b"), str(path))
    assert result["entries"][0]["original"]["width"] == 1300


def test_pack_failed_install_preserves_existing_entries_and_cleans_temporary_files(tmp_path, monkeypatch):
    library = AssetLibrary(tmp_path / "library")
    existing = packs.install_builtin(library, "school-lab")
    before = library.list()
    path = tmp_path / "shared.badpack"
    packs.export_pack(library, [entry["id"] for entry in existing], str(path))
    replace = os.replace
    written = 0

    def fail_second_entry(source, destination):
        nonlocal written
        if destination.suffix == ".json":
            written += 1
            if written == 2:
                raise OSError("disk full")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_entry)
    with pytest.raises(EngineError, match="no new library entries"):
        packs.import_pack(library, str(path))
    assert written == 2  # exercise rollback after the first new record reached disk
    assert library.list() == before
    assert not list(library.root.glob("*.tmp"))
    session = Session.new()
    restored = library.restore(session, existing[0]["id"])
    assert session.artifacts.data(restored["working"]["id"]) == library._blob(library.get(existing[0]["id"]).artifact)


def test_pack_rejects_unsupported_manifest(tmp_path):
    path = tmp_path / "unknown.badpack"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pack.json", json.dumps({"schema": 2, "entries": []}))
    with pytest.raises(EngineError, match="unsupported"):
        packs.import_pack(AssetLibrary(tmp_path / "target"), str(path))


def test_pack_refuses_symlink_and_duplicate_members(tmp_path):
    library = AssetLibrary(tmp_path / "source")
    entry = packs.install_builtin(library, "conspiracy")[0]
    for kind in ("symlink", "duplicate"):
        path = tmp_path / f"{kind}.badpack"
        packs.export_pack(library, [entry["id"]], str(path))
        with zipfile.ZipFile(path, "a") as archive:
            if kind == "symlink":
                info = zipfile.ZipInfo("linked")
                info.external_attr = 0o120777 << 16
                archive.writestr(info, "/etc/passwd")
            else:
                with pytest.warns(UserWarning, match="Duplicate"):
                    archive.writestr("pack.json", "{}")
        with pytest.raises(EngineError):
            packs.import_pack(AssetLibrary(tmp_path / kind), str(path))


def test_pack_size_limit_is_checked_before_image_decode(tmp_path, monkeypatch):
    library = AssetLibrary(tmp_path / "source")
    entry = packs.install_builtin(library, "conspiracy")[0]
    path = tmp_path / "oversized.badpack"
    packs.export_pack(library, [entry["id"]], str(path))
    monkeypatch.setattr(packs, "MAX_ENTRY", 1)
    with pytest.raises(EngineError, match="size limit"):
        packs.import_pack(AssetLibrary(tmp_path / "target"), str(path))


def test_pack_directory_is_bounded_before_allocation(tmp_path, monkeypatch):
    path = tmp_path / "directory.badpack"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pack.json", "{}")
    raw = bytearray(path.read_bytes())
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<I", raw, end + 12, packs.MAX_DIRECTORY + 1)
    path.write_bytes(raw)

    def forbidden(*a, **kw):
        pytest.fail("ZipFile allocated an unchecked pack directory")

    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    target = AssetLibrary(tmp_path / "target")
    with pytest.raises(EngineError, match="directory metadata"):
        packs.import_pack(target, str(path))
    assert not target.list()


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_pack_rejects_unbounded_decompressors(tmp_path, compression):
    path = tmp_path / "compression.badpack"
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        archive.writestr("pack.json", '{"schema": 1, "entries": []}')
    target = AssetLibrary(tmp_path / "target")
    with pytest.raises(EngineError, match="compression"):
        packs.import_pack(target, str(path))
    assert not target.list()


def test_pack_lying_size_header_cannot_request_unbounded_inflate(tmp_path, monkeypatch):
    path = tmp_path / "lying-size.badpack"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack.json", b" " * (8 * 2**20))
    raw = bytearray(path.read_bytes())
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<I", raw, central + 24, 64)
    struct.pack_into("<I", raw, 22, 64)
    path.write_bytes(raw)
    original = zipfile.ZipExtFile.read
    requests = []

    def bounded_read(file, n=-1):
        assert 0 < n <= packs.READ_CHUNK, "unbounded inflate request"
        requests.append(n)
        return original(file, n)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", bounded_read)
    target = AssetLibrary(tmp_path / "target")
    with pytest.raises(EngineError):
        packs.import_pack(target, str(path))
    assert requests and not target.list()


def test_pack_rpc_management_is_user_only(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from badshop.server.packs_api import register
    from badshop.server.rpc import Dispatcher, FORBIDDEN

    async def blocking(fn, *args):
        return fn(*args)

    app = SimpleNamespace(library=AssetLibrary(tmp_path), dispatcher=Dispatcher(), _blocking=blocking)
    register(app)
    message = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "packs.install", "params": {"id": "school-lab"}})
    denied = json.loads(asyncio.run(app.dispatcher.handle(message, "cli:codex")))
    assert denied["error"]["code"] == FORBIDDEN
    assert not app.library.list()
    allowed = json.loads(asyncio.run(app.dispatcher.handle(message, "user")))
    assert len(allowed["result"]) == 4
