"""Opt-in native pixels on a private Xvfb; never capture the user's display."""
import os
import ctypes

import pytest

from badshop.session.media import MediaSources
from badshop.session import capture, project
from badshop.server.rpc import FORBIDDEN
from badshop.session.worker import WorkerExecutor
from test_server_app import Client, Failed, run, env as env


def test_cancelled_capture_has_no_preview_or_project_data(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "capture_image", lambda: None)
    media = MediaSources(tmp_path / "cache")
    assert media.capture(_scratch=tmp_path) is None
    assert not (tmp_path / "cache").exists()
    assert not list(tmp_path.iterdir())


def test_capture_and_discard_are_user_only(env):
    async def scenario(app):
        agent = Client(app, "agent:test")
        for method, params in [("media.capture", {}), ("media.discard", {"preview_id": "a" * 32})]:
            with pytest.raises(Failed) as error:
                await agent.call(method, **params)
            assert error.value.code == FORBIDDEN
    run(scenario)


@pytest.mark.skipif(os.environ.get("BADSHOP_PRIVATE_CAPTURE_TEST") != "1", reason="requires opt-in private Xvfb")
def test_private_desktop_region_annotation_and_reopen(env, tmp_path):
    assert os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    xlib = ctypes.CDLL("libX11.so.6")
    xlib.XOpenDisplay.argtypes, xlib.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
    xlib.XDefaultRootWindow.argtypes, xlib.XDefaultRootWindow.restype = [ctypes.c_void_p], ctypes.c_ulong
    xlib.XSetWindowBackground.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    xlib.XClearWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = xlib.XOpenDisplay(None)
    assert display
    root = xlib.XDefaultRootWindow(display)
    xlib.XSetWindowBackground(display, root, 0x123456)
    xlib.XClearWindow(display, root)
    xlib.XSync(display, 0)

    async def scenario(app):
        user = Client(app, "user")
        before = app.session.data.model_dump()
        preview = await user.call("media.capture")
        assert app.session.data.model_dump() == before
        assert (preview["width"], preview["height"]) == (800, 600)
        result = await user.call("media.import", preview_id=preview["id"], candidate_ids=["0"], crop=[10, 20, 110, 100])
        output = result["artifacts"][0]["id"]
        assert app.session.artifacts.image(output).getpixel((50, 40))[:3] == (18, 52, 86)
        assert len(app.session.artifacts.ids()) == 1
        assert app.session.artifacts.meta[output].original_id is None
        assert app.session.artifacts.meta[output].source.kind == "screen-capture"
        assert app.session.artifacts.image(output).size == (100, 80)
        step = await user.call("tools.run", tool="draw", params={"image": output, "rect": [[5, 5, 90, 70]], "color": "white", "width": 2})
        annotated = step["outputs"][0]
        assert app.session.artifacts.image(annotated).getpixel((5, 5))[:3] == (255, 255, 255)
        assert app.session.artifacts.image(annotated).getpixel((50, 40))[:3] == (18, 52, 86)
        await user.call("media.discard", preview_id=preview["id"])
        with pytest.raises(Failed, match="expired"):
            await user.call("media.import", preview_id=preview["id"], candidate_ids=["0"])
        file = tmp_path / "capture.badshop"
        project.save(app.session, file)
        reopened = project.open_project(file)
        assert reopened.artifacts.data(annotated) == app.session.artifacts.data(annotated)
        assert reopened.data.steps[-1].params["rect"] == [[5, 5, 90, 70]]
        await user.call("history.undo")
        assert annotated not in app.session.visible_artifact_ids()
        await user.call("history.redo")
        assert annotated in app.session.visible_artifact_ids()
    try:
        run(scenario, factory=WorkerExecutor)
    finally:
        xlib.XCloseDisplay(display)
