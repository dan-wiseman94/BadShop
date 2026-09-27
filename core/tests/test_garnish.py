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
    ["watermark", "lincoln.png", "--text", "made in badshop"],
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
    with pytest.raises(EngineError, match="give at or repeat"):
        run_tool("sparkle", {"image": ref}, store)
    with pytest.raises(EngineError, match="name a watermark"):
        run_tool("watermark", {"image": ref}, store)
