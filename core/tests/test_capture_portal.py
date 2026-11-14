"""Wayland portal protocol against a fixture service on a private session bus."""
import asyncio
import os

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session.capture import capture_image


@pytest.mark.skipif(os.environ.get("BADSHOP_PRIVATE_CAPTURE_TEST") != "1", reason="requires private dbus-run-session")
@pytest.mark.parametrize("response", ["success", "cancel", "invalid-uri"])
def test_portal_response_and_request_cleanup(tmp_path, monkeypatch, response):
    from dbus_fast import Message, Variant
    from dbus_fast.aio import MessageBus

    monkeypatch.setenv("WAYLAND_DISPLAY", "private-portal-fixture")
    source = tmp_path / "portal.png"
    Image.new("RGB", (80, 60), (18, 52, 86)).save(source)
    calls = []

    async def scenario():
        bus = await MessageBus().connect()
        await bus.request_name("org.freedesktop.portal.Desktop")

        def receive(message):
            if message.member == "Introspect":
                return Message.new_method_return(message, signature="s", body=["<node/>"])
            if message.member == "Screenshot":
                parent, options = message.body
                assert parent == "" and options["interactive"].value is True
                handle = "/org/freedesktop/portal/desktop/request/" + message.sender[1:].replace(".", "_") + "/" + options["handle_token"].value
                calls.append("Screenshot")
                uri = source.as_uri() if response != "invalid-uri" else "https://example.invalid/capture.png"
                signal = Message.new_signal(handle, "org.freedesktop.portal.Request", "Response",
                    signature="ua{sv}", body=[1 if response == "cancel" else 0, {"uri": Variant("s", uri)}])
                asyncio.get_running_loop().call_later(.01, lambda: bus.send(signal))
                return Message.new_method_return(message, signature="o", body=[handle])
            if message.member == "Close":
                calls.append("Close")
                return Message.new_method_return(message)

        bus.add_message_handler(receive)
        try:
            if response == "invalid-uri":
                with pytest.raises(EngineError, match="unsupported screenshot location"):
                    await asyncio.to_thread(capture_image)
            else:
                image = await asyncio.to_thread(capture_image)
                if response == "cancel":
                    assert image is None
                else:
                    with image:
                        assert image.size == (80, 60) and image.getpixel((10, 10))[:3] == (18, 52, 86)
            assert calls == ["Screenshot", "Close"]
            assert source.exists()  # portal owns its returned file
        finally:
            bus.disconnect()
            await bus.wait_for_disconnect()
    asyncio.run(scenario())
