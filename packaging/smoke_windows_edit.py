"""Exercise editing and native file dialogs in the installed Windows application."""

import base64
import contextlib
import ctypes
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright
from pywinauto import Desktop

from badshop.session.project import open_project
from native_windows import screenshot as capture_window
from smoke_desktop import smoke


def choose_file(pid: int, window: int, path: Path) -> None:
    """Use the owned Windows common dialog, scoped to the app and its window."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    visit_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [visit_type, wintypes.LPARAM]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND

    # The Common Item Dialog can be visible in Win32 while UIA's Desktop
    # enumeration misses it. Find the native HWND first, using the owner chain.
    dialogs = []

    @visit_type
    def visit(hwnd, _):
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(hwnd, name, len(name))
        if name.value != '#32770' or not user.IsWindowVisible(hwnd):
            return True
        owner = user.GetWindow(hwnd, 4)  # GW_OWNER
        while owner and owner != window:
            owner = user.GetWindow(owner, 4)
        if owner == window:
            dialogs.append(hwnd)
        return True

    deadline = time.monotonic() + 20
    while not dialogs and time.monotonic() < deadline:
        user.EnumWindows(visit, 0)
        if not dialogs:
            time.sleep(.2)
    assert len(dialogs) == 1, f'Expected one visible native file dialog owned by BadShop PID {pid}, got {dialogs}'
    hwnd, = dialogs
    dialog = Desktop(backend='uia').window(handle=hwnd)
    filename = dialog.child_window(auto_id='1001', control_type='Edit')
    if not filename.exists(timeout=1):
        filename = dialog.child_window(auto_id='1148', control_type='ComboBox').child_window(control_type='Edit')
    filename.set_edit_text(str(path))
    dialog.child_window(auto_id='1', control_type='Button').invoke()
    deadline = time.monotonic() + 20
    while user.IsWindowVisible(hwnd):
        assert time.monotonic() < deadline, f'Native file dialog did not close for {path.name}'
        time.sleep(.2)


def viewer_hash(page: Page) -> str:
    image = page.locator('.canvas-image')
    expect(image).to_be_visible(timeout=20000)
    expect(image).to_have_attribute('src', re.compile(r'^data:image/[^;]+;base64,.+'))
    page.wait_for_function("image => image.complete && image.naturalWidth > 0", arg=image.element_handle())
    encoded = image.get_attribute('src').split(',', 1)[1]
    return hashlib.sha256(base64.b64decode(encoded)).hexdigest()


def debugger_url(profile: Path) -> str:
    """Read the ephemeral browser endpoint that WebView2 wrote inside this launch's profile."""
    marker = profile / 'EBWebView' / 'DevToolsActivePort'
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with contextlib.suppress(FileNotFoundError, PermissionError):
            lines = marker.read_text(encoding='ascii').splitlines()
            if len(lines) >= 2 and lines[0].isdigit() and re.fullmatch(r'/devtools/browser/[\w-]+', lines[1]):
                port = int(lines[0])
                if 0 < port <= 65535:
                    return f'ws://127.0.0.1:{port}{lines[1]}'
        time.sleep(.2)
    raise RuntimeError(f'WebView2 did not publish a debugger endpoint in its private profile: {marker}')


@contextlib.contextmanager
def runner_webview_policy(executable: Path, profile: Path):
    """WebView2 ignores environment overrides for elevated hosts on Actions."""
    if os.environ.get('BADSHOP_SMOKE_WEBVIEW_POLICY') != '1':
        yield
        return
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('WebView2 machine policy is reserved for the disposable Actions runner')
    import winreg

    def restore(key, previous):
        if previous is None:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, executable.name)
        else:
            value, kind = previous
            winreg.SetValueEx(key, executable.name, 0, kind, value)

    settings = {'AdditionalBrowserArguments': '--remote-debugging-port=0',
                'UserDataFolder': str(profile.resolve())}
    with contextlib.ExitStack() as stack:
        for name, value in settings.items():
            path = rf'SOFTWARE\Policies\Microsoft\Edge\WebView2\{name}'
            key = stack.enter_context(winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                                         winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE))
            try:
                previous = winreg.QueryValueEx(key, executable.name)
            except FileNotFoundError:
                previous = None
            stack.callback(restore, key, previous)
            winreg.SetValueEx(key, executable.name, 0, winreg.REG_SZ, value)
        yield


def smoke_editing(executable: Path, screenshot: Path, fixture: Path, root: Path) -> None:
    project = root / 'native-edit.badshop'
    summary = {'status': 'failed', 'stages': []}
    screenshot.parent.mkdir(parents=True, exist_ok=True)

    def run(shot: Path, scenario: Callable[[Page, int, int, Callable[[], None], Path], None]) -> None:
        profile = root / f'{shot.stem}-webview'
        assert not profile.exists(), 'The Windows test requires a fresh WebView2 profile'

        def exercise(pid: int, window: int, close: Callable[[], None]) -> None:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(debugger_url(profile), timeout=15000)
                page, = [page for context in browser.contexts for page in context.pages
                         if page.url.startswith('http://tauri.localhost')]
                page.set_default_timeout(15000)
                trace = shot.with_suffix('.zip')
                page.context.tracing.start(screenshots=True, snapshots=True)
                try:
                    expect(page.get_by_text('Connected', exact=True)).to_be_visible(timeout=15000)
                    page.get_by_role('button', name='Edit a photo without AI', exact=True).click()
                    scenario(page, pid, window, close, trace)
                except Exception:
                    with contextlib.suppress(PlaywrightError):
                        page.context.tracing.stop(path=trace)
                    with contextlib.suppress(OSError, RuntimeError):
                        if not page.is_closed():
                            capture_window(window, shot.with_name(f'{shot.stem}-failure.png').resolve())
                    raise

        with runner_webview_policy(executable, profile):
            smoke([str(executable)], shot, webview_profile=profile, exercise=exercise)

    output_hash = ''

    def edit(page: Page, pid: int, window: int, close: Callable[[], None], trace: Path) -> None:
        nonlocal output_hash
        page.get_by_role('button', name='Attach images', exact=True).click()
        choose_file(pid, window, fixture)
        imported_hash = viewer_hash(page)
        page.get_by_role('button', name='Run tool', exact=True).click()
        palette = page.get_by_role('dialog', name='Run a tool')
        palette.get_by_role('textbox', name='Search tools').fill('deepfry')
        palette.get_by_role('button', name=re.compile(r'^deepfry\b')).click()
        palette.get_by_role('button', name='Run tool', exact=True).click()
        step = page.get_by_role('region', name='Steps timeline').locator('.step').filter(has_text='deepfry')
        expect(step).to_contain_text('done', ignore_case=True, timeout=20000)
        expect(page.locator('.canvas-image')).to_have_attribute('alt', re.compile(r'_deepfried$'))
        output_hash = viewer_hash(page)
        assert output_hash != imported_hash, 'The deterministic edit did not change the displayed image'
        close()
        guard = page.get_by_role('dialog', name=re.compile(r'^Save changes to'))
        guard.get_by_role('button', name='Cancel', exact=True).click()
        expect(guard).to_be_hidden()
        assert viewer_hash(page) == output_hash and not project.exists()
        summary['stages'].append('edited and cancelled native close')
        capture_window(window, screenshot.with_name('native-edited.png').resolve())
        close()
        guard.get_by_role('button', name='Save & close', exact=True).click()
        page.context.tracing.stop(path=trace)
        choose_file(pid, window, project)

    def reopen(page: Page, pid: int, window: int, close: Callable[[], None], trace: Path) -> None:
        page.locator('.session-name').click()
        page.get_by_role('button', name=re.compile(r'^Open session')).click()
        choose_file(pid, window, project)
        step = page.get_by_role('region', name='Steps timeline').locator('.step').filter(has_text='deepfry')
        expect(step).to_contain_text('done', ignore_case=True, timeout=20000)
        step.click()
        expect(page.locator('.canvas-image')).to_have_attribute('alt', re.compile(r'_deepfried$'))
        assert viewer_hash(page) == output_hash, 'Reopened viewer did not show the saved image'
        capture_window(window, screenshot.with_name('native-reopened.png').resolve())
        page.context.tracing.stop(path=trace)
        close()

    try:
        run(screenshot, edit)
        saved = open_project(project, output_dir=root)
        step, = saved.data.steps
        assert (step.tool, step.status, step.outputs) == ('deepfry', 'done', [output_hash])
        assert hashlib.sha256(saved.artifacts.data(output_hash)).hexdigest() == output_hash
        summary['stages'].append('saved project via native dialog and closed cleanly')
        summary['output_sha256'] = output_hash
        run(screenshot.with_name('native-relaunch.png'), reopen)
        summary['stages'].append('reopened via native dialog, verified output and closed cleanly')
        summary['status'] = 'passed'
    finally:
        screenshot.with_name('summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
