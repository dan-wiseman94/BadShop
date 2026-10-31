"""Small platform adapters for the installed desktop lifecycle smoke."""
import ctypes
import subprocess
import sys
from pathlib import Path


def visible_window(pid: int) -> int | None:
    if sys.platform == 'win32':
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        windows = []

        @callback
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd, title, len(title))
            if owner.value == pid and user.IsWindowVisible(hwnd) and title.value == 'badshop':
                windows.append(hwnd)
            return True

        user.EnumWindows(visit, 0)
        return windows[0] if windows else None
    if sys.platform == 'darwin':
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly,
                                                   Quartz.kCGNullWindowID)
        for window in windows:
            bounds = window.get('kCGWindowBounds', {})
            if (window.get('kCGWindowOwnerPID') == pid and window.get('kCGWindowLayer') == 0
                    and bounds.get('Width', 0) >= 500 and bounds.get('Height', 0) >= 300):
                return int(window['kCGWindowNumber'])
        return None
    if pid == 0:
        # Flatpak deliberately omits _NET_WM_PID. The harness may use this only
        # on its dedicated X server, where exactly one application was launched.
        result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^badshop$'],
                                capture_output=True, text=True, check=False)
        matches = result.stdout.splitlines()
        return int(matches[0]) if len(matches) == 1 else None
    # X11 reports the PID inside Flatpak's namespace. Match only aliases of the
    # owned process, and require both PID and title (xdotool defaults to OR).
    aliases = {pid}
    status = Path(f'/proc/{pid}/status')
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith('NSpid:'):
                aliases.update(int(value) for value in line.split()[1:])
    for alias in aliases:
        result = subprocess.run(['xdotool', 'search', '--all', '--onlyvisible', '--pid', str(alias),
                                 '--name', '^badshop$'], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return int(result.stdout.splitlines()[0])
    return None



def screenshot(window: int, path: Path) -> None:
    if sys.platform == 'win32':
        from ctypes import wintypes

        from PIL import ImageGrab
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        user.SetForegroundWindow(window)
        rect = wintypes.RECT()
        if not user.GetWindowRect(window, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(path)
    elif sys.platform == 'darwin':
        subprocess.run(['screencapture', '-x', '-l', str(window), str(path)], check=True, timeout=15)
    else:
        subprocess.run(['import', '-window', str(window), str(path)], check=True, timeout=15)


def normal_close(pid: int, window: int) -> None:
    if sys.platform == 'win32':
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        if not user.PostMessageW(window, 0x0010, 0, 0):  # WM_CLOSE, not process termination
            raise ctypes.WinError(ctypes.get_last_error())
    elif sys.platform == 'darwin':
        from AppKit import NSRunningApplication
        application = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if application is None:
            raise RuntimeError('macOS could not find the running application')
        # The frontend may defer Quit while its asynchronous close handler runs.
        # The harness verifies the eventual exit instead of trusting this return value.
        application.terminate()
    else:
        from smoke_desktop import close_window
        close_window(window)
