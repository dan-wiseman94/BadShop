"""Explicit user capture through the OS; never exposed as an agent pixel tool."""
import asyncio
import os
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageGrab

from badshop.engine.errors import EngineError


async def _portal_capture():
    from dbus_fast import Message, MessageType, Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.errors import DBusError

    service = "org.freedesktop.portal.Desktop"
    object_path = "/org/freedesktop/portal/desktop"
    interface = "org.freedesktop.portal.Request"
    bus = await MessageBus().connect()
    handle = None
    try:
        await bus.introspect(service, object_path)  # activates the desktop portal if needed
        owner = await bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                                       interface="org.freedesktop.DBus", member="GetNameOwner",
                                       signature="s", body=[service]))
        if owner.message_type == MessageType.ERROR:
            raise EngineError("the desktop screenshot portal is unavailable")
        token = "badshop_" + uuid.uuid4().hex
        handle = f"{object_path}/request/{bus.unique_name[1:].replace('.', '_')}/{token}"
        response = asyncio.get_running_loop().create_future()

        def receive(message):
            if (message.message_type == MessageType.SIGNAL and message.sender == owner.body[0]
                    and message.path == handle and message.interface == interface
                    and message.member == "Response" and not response.done()):
                response.set_result(message.body)

        bus.add_message_handler(receive)
        match = await bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch", signature="s",
            body=[f"type='signal',sender='{service}',interface='{interface}',member='Response',path='{handle}'"]))
        if match.message_type == MessageType.ERROR:
            raise EngineError("could not listen for screenshot permission")
        request = await bus.call(Message(destination=service, path=object_path,
            interface="org.freedesktop.portal.Screenshot", member="Screenshot", signature="sa{sv}",
            body=["", {"handle_token": Variant("s", token), "interactive": Variant("b", True)}]))
        if request.message_type == MessageType.ERROR or request.body != [handle]:
            raise EngineError("the desktop could not start a screenshot request")
        code, result = await response
        if code == 1:
            return None
        if code != 0 or "uri" not in result:
            raise EngineError("the desktop could not capture a screenshot")
        uri = urlsplit(result["uri"].value)
        if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
            raise EngineError("the desktop returned an unsupported screenshot location")
        return Path(unquote(uri.path))
    except DBusError as error:
        raise EngineError("the desktop screenshot portal is unavailable",
                          hint="enable your desktop's screenshot portal and try again") from error
    finally:
        try:
            if handle and bus.connected:
                with suppress(OSError, TimeoutError):
                    await asyncio.wait_for(bus.call(Message(destination=service, path=handle,
                        interface=interface, member="Close")), timeout=2)
        finally:
            bus.disconnect()
            await bus.wait_for_disconnect()


def capture_image():
    """Return owned screenshot pixels, or None when the OS chooser was cancelled."""
    try:
        if sys.platform == "linux" and os.environ.get("WAYLAND_DISPLAY"):
            path = asyncio.run(asyncio.wait_for(_portal_capture(), timeout=90))
            if path is None:
                return None
            # The portal owns its file; copy pixels without deleting user/portal data.
            from badshop.session.media import source_bytes, small_image
            import io
            with Image.open(io.BytesIO(source_bytes(path)), formats=("PNG",)) as image:
                return small_image(image)
        return ImageGrab.grab(all_screens=True, xdisplay="" if sys.platform == "linux" else None)
    except (OSError, TimeoutError) as error:
        raise EngineError("screen capture is unavailable or timed out",
                          hint="allow screenshot access in your OS settings, then try again") from error
