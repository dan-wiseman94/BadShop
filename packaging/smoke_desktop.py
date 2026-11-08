"""Native source or installed desktop smoke; on Linux use a dedicated X server.

xvfb-run -a uv run --project core python packaging/smoke_desktop.py \
    --screenshot /tmp/badshop.png -- /path/to/installed/badshop-desktop

Linux needs Xvfb, xdotool, xclip, libX11 and ImageMagick; macOS needs PyObjC Cocoa/Quartz.
Requires a visible window, a renderer/core socket, a nonblank content screenshot,
and normal window close/application quit without surviving child processes.
"""
import argparse
import ctypes
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import psutil
from native_windows import normal_close, visible_window
from native_windows import screenshot as capture_window
from PIL import Image


def close_window(window: int) -> None:
    """Send the window manager's close request; xdotool windowclose destroys the drawable."""
    class Data(ctypes.Union):
        _fields_ = [('bytes', ctypes.c_char * 20), ('shorts', ctypes.c_short * 10),
                    ('longs', ctypes.c_long * 5)]

    class ClientMessage(ctypes.Structure):
        _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                    ('display', ctypes.c_void_p), ('window', ctypes.c_ulong),
                    ('message_type', ctypes.c_ulong), ('format', ctypes.c_int), ('data', Data)]

    class Event(ctypes.Union):
        _fields_ = [('client', ClientMessage), ('padding', ctypes.c_long * 24)]

    xlib = ctypes.CDLL('libX11.so.6')
    xlib.XOpenDisplay.argtypes, xlib.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
    xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
                               ctypes.POINTER(Event)]
    xlib.XFlush.argtypes = xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = xlib.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Could not open the dedicated X display')
    try:
        event = Event()
        event.client.type, event.client.send_event = 33, 1  # ClientMessage
        event.client.display, event.client.window = display, window
        event.client.message_type = xlib.XInternAtom(display, b'WM_PROTOCOLS', False)
        event.client.format = 32
        event.client.data.longs[0] = xlib.XInternAtom(display, b'WM_DELETE_WINDOW', False)
        xlib.XSendEvent(display, window, False, 0, ctypes.byref(event))
        xlib.XFlush(display)
    finally:
        xlib.XCloseDisplay(display)


def core_connections(core: psutil.Process) -> tuple[list[int], int]:
    if sys.platform == 'darwin':
        # macOS restricts psutil's system TCP table even for a process we own.
        result = subprocess.run(['lsof', '-nP', '-a', '-p', str(core.pid), '-iTCP', '-F', 'nT'],
                                capture_output=True, text=True, check=False, timeout=5)
        ports = []
        endpoint = ''
        established = 0
        for line in result.stdout.splitlines():
            if line.startswith('n'):
                endpoint = line[1:]
            elif line == 'TST=LISTEN' and endpoint.startswith('127.0.0.1:'):
                ports.append(int(endpoint.rsplit(':', 1)[1]))
            elif line == 'TST=ESTABLISHED':
                established += 1
        return ports, established
    sockets = core.net_connections('tcp')
    return ([c.laddr.port for c in sockets if c.status == 'LISTEN' and c.laddr.ip == '127.0.0.1'],
            sum(c.status == 'ESTABLISHED' for c in sockets))


def is_core(process: psutil.Process) -> bool:
    """Recognize the frozen core and the Python entry point, never the uv wrapper."""
    try:
        name = process.name().lower()
        if name in ('badshop-core', 'badshop-core.exe'):
            return True
        args = process.cmdline()
        return name.startswith('python') and 'serve' in args and (
            any(Path(arg).name == 'badshop-core' for arg in args[1:])
            or any(args[i:i + 2] == ['-m', 'badshop.server'] for i in range(1, len(args) - 1))
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def renderer_is_ready(path: Path, nonce: str, ports: list[int] | None = None) -> bool:
    """TCP establishment/first paint can still be an unauthenticated loading UI."""
    try:
        state = json.loads(path.read_text())
        return (isinstance(state, dict) and state.get('nonce') == nonce
                and isinstance(state.get('session_id'), str) and bool(state['session_id'])
                and type(state.get('tool_count')) is int and state['tool_count'] > 0
                and state.get('clipboard_pixels') is True
                and (ports is None or (state.get('port') in ports
                     and type(state.get('revision')) is int and state['revision'] >= 0)))
    except (OSError, ValueError):  # a probe write can overlap this read
        return False


def check_native_log(text: str) -> None:
    """A successful shell exit does not excuse a crashed WebKit child on teardown."""
    fatal = ('corrupted double-linked list', 'double free or corruption', 'free(): invalid pointer',
             'malloc():', 'addresssanitizer:', 'heap corruption detected', 'segmentation fault')
    for marker in fatal:
        if marker in text.lower():
            raise AssertionError(f'Native process reported {marker!r}; see retained native log')


def wait_renderer(proc, path: Path, ports: list[int], nonce: str, **expected) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        assert proc.poll() is None, 'Native shell exited during an interaction'
        try:
            if renderer_is_ready(path, nonce, ports):
                state = json.loads(path.read_text())
                if all(state.get(key) == value for key, value in expected.items()):
                    return state
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise AssertionError(f'Renderer did not reach {expected}')


def native_keys(window: int, *keys: str) -> None:
    subprocess.run(['xdotool', 'windowfocus', '--sync', str(window), 'key', '--clearmodifiers', *keys],
                   check=True, timeout=5)


def isolated_command(command: list[str], root: Path, env: dict) -> list[str]:
    if Path(command[0]).name == 'flatpak' and len(command) > 1 and command[1] == 'run':
        # Flatpak has private /tmp. Expose only this harness-owned directory.
        return [*command[:2], f'--filesystem={root}',
                f'--env=BADSHOP_SMOKE_READY_FILE={env["BADSHOP_SMOKE_READY_FILE"]}',
                f'--env=BADSHOP_SMOKE_NONCE={env["BADSHOP_SMOKE_NONCE"]}', *command[2:]]
    return command


def smoke(command: list[str], screenshot: Path | None, startup_timeout: float = 90,
          restart_core: bool = False, *,
          webview_profile: Path | None = None,
          exercise: Callable[[int, int, Callable[[], None]], None] | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix='badshop-native-smoke-') as folder:
        root = Path(folder)
        env = dict(os.environ)
        # Preserve the real installation lookup before isolating XDG application data.
        env.setdefault('FLATPAK_USER_DIR', str(Path(env.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'flatpak'))
        if sys.platform == 'linux':
            env['GDK_BACKEND'] = 'x11'
            # Private Xvfb has no accelerated display. Mesa 26.2.2's Gallium
            # teardown can abort WebKitWebProcess even after a clean shell exit.
            # This harness setting does not change production Wayland rendering.
            env.setdefault('WEBKIT_DISABLE_COMPOSITING_MODE', '1')
        for key, suffix in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state'),
                            ('BADSHOP_CONFIG_DIR', 'core-config'), ('BADSHOP_DATA_DIR', 'core-data'),
                            ('BADSHOP_LOG_DIR', 'logs'), ('BADSHOP_OUT', 'output')]:
            env[key] = str(root / suffix)
        env.pop('WAYLAND_DISPLAY', None)
        env.pop('BADSHOP_FAKE_PROVIDER', None)
        if sys.platform == 'win32':
            env['WEBVIEW2_USER_DATA_FOLDER'] = str((webview_profile or root / 'webview').resolve())
            if webview_profile is not None:
                env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--remote-debugging-port=0'
        ready_path = root / 'renderer-ready.json'
        nonce = secrets.token_hex(16)
        env['BADSHOP_SMOKE_READY_FILE'] = str(ready_path)
        env['BADSHOP_SMOKE_NONCE'] = nonce
        log_path = root / 'desktop.log'
        with log_path.open('w') as log:
            proc = subprocess.Popen(isolated_command(command, root, env), env=env, stdout=log, stderr=subprocess.STDOUT)
            children = []
            try:
                deadline = time.monotonic() + startup_timeout
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f'shell exited {proc.returncode}')
                    children = psutil.Process(proc.pid).children(recursive=True)
                    cores = [p for p in children if is_core(p)]
                    if cores:
                        core = cores[0]
                        ports, connected = core_connections(core)
                        window = None
                        window_pid = proc.pid
                        for candidate in [psutil.Process(proc.pid), *children]:
                            window = visible_window(candidate.pid)
                            if window:
                                window_pid = candidate.pid
                                break
                        if not window and sys.platform == 'linux' and Path(command[0]).name == 'flatpak':
                            window = visible_window(0)
                        if ports and connected and window and renderer_is_ready(ready_path, nonce, ports):
                            break
                    time.sleep(.2)
                else:
                    raise RuntimeError(f'No rendered, authenticated session after {startup_timeout}s')
                print(json.dumps({'shell_pid': proc.pid, 'core_pid': core.pid,
                                  'core_executable': core.exe(), 'listen_ports': ports,
                                  'established_connections': connected, 'renderer_ready': True}), flush=True)
                exercise_close = restart_core and sys.platform == 'linux'
                session_id = None
                if exercise_close:
                    state = wait_renderer(proc, ready_path, ports, nonce)
                    if state['welcome']:
                        native_keys(window, 'Return')  # Welcome: Start with a quick idea
                        wait_renderer(proc, ready_path, ports, nonce, welcome=False)
                    # Exercise native paste on this private display without relying
                    # on screen coordinates that change with the workspace layout.
                    pasted = root / 'clipboard.png'
                    Image.new('RGBA', (40, 30), (30, 160, 240, 255)).save(pasted)
                    clipboard = subprocess.Popen(['xclip', '-selection', 'clipboard', '-t', 'image/png',
                                                  '-i', str(pasted), '-quiet'], stdout=log, stderr=log)
                    try:
                        clipboard_deadline = time.monotonic() + 5
                        while True:
                            observed = subprocess.run(['xclip', '-selection', 'clipboard', '-o', '-t', 'image/png'],
                                                      capture_output=True, timeout=5)
                            if observed.returncode == 0 and observed.stdout == pasted.read_bytes():
                                break
                            assert time.monotonic() < clipboard_deadline, 'Private clipboard was not ready'
                            time.sleep(.05)
                        native_keys(window, 'ctrl+v')
                        state = wait_renderer(proc, ready_path, ports, nonce, unsaved=True)
                    finally:
                        clipboard.terminate()
                        clipboard.wait(timeout=5)
                    session_id = state['session_id']
                if restart_core:
                    old_pid = core.pid
                    ready_path.unlink()
                    core.kill()  # crash only the core owned by this private native run
                    core.wait(timeout=10)
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        assert proc.poll() is None, 'Shell exited while recovering its core'
                        children = psutil.Process(proc.pid).children(recursive=True)
                        candidates = [p for p in children if p.pid != old_pid and is_core(p)]
                        if candidates:
                            core = candidates[0]
                            ports, connected = core_connections(core)
                            if connected and renderer_is_ready(ready_path, nonce, ports):
                                break
                        time.sleep(.2)
                    else:
                        raise RuntimeError('Renderer did not recover to a loaded session after core crash')
                    print(f'Native renderer recovered after core crash: {old_pid} -> {core.pid}', flush=True)
                    if session_id:
                        wait_renderer(proc, ready_path, ports, nonce, session_id=session_id, unsaved=True)
                shot = screenshot or root / 'window.png'
                shot.parent.mkdir(parents=True, exist_ok=True)
                paint_deadline = time.monotonic() + 30
                while True:
                    capture_window(window, shot.resolve())
                    with Image.open(shot) as frame:
                        assert frame.width >= 900 and frame.height >= 600, 'Window capture is smaller than the app minimum'
                        # Connecting the socket can precede WebKit's first paint on CI.
                        # Keep the same content requirement and retain the final frame on failure.
                        content = frame.crop((40, 100, frame.width - 40, frame.height - 40)).convert('L')
                        if content.entropy() > 1:
                            break
                    assert proc.poll() is None, 'Shell exited before its first paint'
                    assert time.monotonic() < paint_deadline, 'Webview screenshot is blank after 30 seconds'
                    time.sleep(.5)
                def close() -> None:
                    nonlocal children
                    children = psutil.Process(proc.pid).children(recursive=True)
                    normal_close(window_pid, window)

                if exercise is None:
                    close()
                    if exercise_close:
                        wait_renderer(proc, ready_path, ports, nonce, close_pending=True)
                        capture_window(window, shot.with_name(shot.stem + '-close.png').resolve())
                        native_keys(window, 'Escape')
                        wait_renderer(proc, ready_path, ports, nonce, close_pending=False, unsaved=True)
                        assert proc.poll() is None, 'Cancel closed the native app'
                        close()
                        wait_renderer(proc, ready_path, ports, nonce, close_pending=True)
                        native_keys(window, 'Tab', 'Return')  # Cancel -> Discard
                else:
                    exercise(window_pid, window, close)
                assert proc.wait(timeout=15) == 0, 'Native close returned a failure exit code'
                _, alive = psutil.wait_procs(children, timeout=5)
                survivors = []
                for child in alive:
                    try:
                        if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                            survivors.append(child.pid)
                    except psutil.NoSuchProcess:
                        pass
                assert not survivors, f'Children survived native close: {survivors}'
                check_native_log(log_path.read_text(errors='replace'))
                if sys.platform == 'darwin':
                    assert 'native Quit routed through project close guard' in log_path.read_text(), \
                        'Native Quit bypassed the unsaved-project close guard'
                print('Native desktop smoke passed: rendered window, authenticated session/catalog, clean close', flush=True)
            finally:
                if proc.poll() is None:
                    children = psutil.Process(proc.pid).children(recursive=True)
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                # The isolated harness owns these children; never leave them behind after a failure.
                for child in children:
                    try:
                        if child.is_running():
                            child.kill()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(children, timeout=5)
                if screenshot:
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    screenshot.with_suffix('.log').write_bytes(log_path.read_bytes())
                    if ready_path.exists():
                        screenshot.with_suffix('.ready.json').write_bytes(ready_path.read_bytes())
                print(log_path.read_text(encoding='utf-8', errors='replace')[-5000:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--restart-core', action='store_true',
                        help='Crash the owned core and require renderer readiness after recovery')
    parser.add_argument('--startup-timeout', type=float, default=90,
                        help='Seconds allowed for startup, including compilation for a source launcher')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('provide the installed desktop command after --')
    if args.startup_timeout <= 0:
        parser.error('--startup-timeout must be positive')
    smoke(command, args.screenshot, args.startup_timeout, args.restart_core)
