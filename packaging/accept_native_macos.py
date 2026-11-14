"""Native macOS project Save/Open acceptance on an isolated Actions desktop."""
import json
import os
import secrets
import time
import zipfile
from pathlib import Path

import psutil

from smoke_desktop import wait_project_pixels
from native_windows import screenshot


def key(code, flags=0):
    import Quartz
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    time.sleep(.2)


def text(value):
    import Quartz
    for char in value:
        for down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(event, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    time.sleep(.2)


def file_dialog(path):
    import Quartz
    time.sleep(1)
    key(5, Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift)  # Go to folder
    text(str(path))
    key(36)
    time.sleep(1)
    key(36)


def editing(pid, window, close, output):
    import AppKit
    import Quartz
    from PIL import Image
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    env = psutil.Process(pid).environ()
    ready = Path(env['BADSHOP_SMOKE_READY_FILE'])
    root = ready.parent

    def state(**expected):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            value = json.loads(ready.read_text())
            if all(value.get(k) == v for k, v in expected.items()):
                return value
            time.sleep(.2)
        screenshot(window, output / 'mac-dialog-failure.png')
        raise AssertionError(f'Native Mac state did not reach {expected}: {value}')

    AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid).activateWithOptions_(
        AppKit.NSApplicationActivateIgnoringOtherApps)
    time.sleep(.5)
    if state()['welcome']:
        key(36)
        state(welcome=False)
    image = root / 'native-input.png'
    Image.new('RGBA', (40, 30), (30, 160, 240, 255)).save(image)
    clipboard = AppKit.NSPasteboard.generalPasteboard()
    clipboard.clearContents()
    assert clipboard.setData_forType_(image.read_bytes(), AppKit.NSPasteboardTypePNG)
    key(9, Quartz.kCGEventFlagMaskCommand)  # Paste
    current = state(unsaved=True)
    pixels = image.read_bytes()
    autosave = root / 'core-data/autosave/session.badshop'
    wait_project_pixels(autosave, current['session_id'], pixels)
    saved = root / 'native-saved.badshop'
    key(1, Quartz.kCGEventFlagMaskCommand)  # Save
    file_dialog(saved)
    state(unsaved=False)
    wait_project_pixels(saved, current['session_id'], pixels)
    reopened = root / 'native-open.badshop'
    identity = secrets.token_hex(8)
    with zipfile.ZipFile(saved) as source, zipfile.ZipFile(reopened, 'w') as target:
        for member in source.infolist():
            data = source.read(member)
            if member.filename == 'session.json':
                document = json.loads(data)
                document['id'] = identity
                document['name'] = 'Native Mac reopened project'
                data = json.dumps(document).encode()
            target.writestr(member, data)
    key(31, Quartz.kCGEventFlagMaskCommand)  # Open
    file_dialog(reopened)
    state(session_id=identity, unsaved=False)
    wait_project_pixels(autosave, identity, pixels)
    from accept_native_visual import NativeLabels
    from accept_clipboard import paste_into_browser
    NativeLabels(window, output).click('Copy image')
    time.sleep(.5)
    paste_into_browser(pixels, output)
    screenshot(window, output / 'mac-native-open.png')
    (output / 'mac-native-files.json').write_text(json.dumps({
        'status': 'passed', 'saved_session': current['session_id'], 'reopened_session': identity,
        'pixel_bytes_verified': True, 'native_dialogs': ['save', 'open']}, indent=2))
    (output / 'mac-native-project.badshop').write_bytes(reopened.read_bytes())
    close()


def open_existing(pid, window, project, output, *, reject_future=False):
    import AppKit
    import Quartz
    from accept_native_visual import NativeLabels
    AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid).activateWithOptions_(
        AppKit.NSApplicationActivateIgnoringOtherApps)
    ready = Path(psutil.Process(pid).environ()['BADSHOP_SMOKE_READY_FILE'])
    if json.loads(ready.read_text())['welcome']:
        key(36)
        time.sleep(1)
    key(31, Quartz.kCGEventFlagMaskCommand)
    file_dialog(project)
    if reject_future:
        NativeLabels(window, output).wait('newer badshop')
    else:
        with zipfile.ZipFile(project) as source:
            identity = json.loads(source.read('session.json'))['id']
            images = [n for n in source.namelist() if n.startswith('artifacts/') and n.endswith('.png')]
            assert len(images) == 1
            pixels = source.read(images[0])
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            state = json.loads(ready.read_text())
            if state['session_id'] == identity and not state['unsaved']:
                break
            time.sleep(.2)
        else:
            screenshot(window, output / 'reopen-failed.png')
            raise AssertionError('Mac did not reopen expected saved project')
        wait_project_pixels(ready.parent / 'core-data/autosave/session.badshop', identity, pixels)
