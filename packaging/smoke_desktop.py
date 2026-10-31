"""Native installed desktop smoke; on Linux use a dedicated X server.

xvfb-run -a uv run --project core python packaging/smoke_desktop.py \
    --screenshot /tmp/badshop.png -- /path/to/installed/badshop-desktop

Linux needs Xvfb, xdotool, libX11 and ImageMagick; macOS needs PyObjC Cocoa/Quartz.
Requires a visible window, a renderer/core socket, a nonblank content screenshot,
and normal window close/application quit without surviving child processes.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
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


def smoke(command: list[str], screenshot: Path | None) -> None:
    with tempfile.TemporaryDirectory(prefix='badshop-native-smoke-') as folder:
        root = Path(folder)
        env = dict(os.environ)
        # Preserve the real installation lookup before isolating XDG application data.
        env.setdefault('FLATPAK_USER_DIR', str(Path(env.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'flatpak'))
        if sys.platform == 'linux':
            env['GDK_BACKEND'] = 'x11'
        for key, suffix in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state'),
                            ('BADSHOP_CONFIG_DIR', 'core-config'), ('BADSHOP_DATA_DIR', 'core-data'),
                            ('BADSHOP_LOG_DIR', 'logs')]:
            env[key] = str(root / suffix)
        env.pop('WAYLAND_DISPLAY', None)
        env.pop('BADSHOP_FAKE_PROVIDER', None)
        log_path = root / 'desktop.log'
        with log_path.open('w') as log:
            proc = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            children = []
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f'shell exited {proc.returncode}')
                    children = psutil.Process(proc.pid).children(recursive=True)
                    cores = [p for p in children if p.name() in ('badshop-core', 'badshop-core.exe')]
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
                        if ports and connected and window:
                            break
                    time.sleep(.2)
                else:
                    raise RuntimeError('No visible window with renderer/core connection after 90 seconds')
                print(json.dumps({'shell_pid': proc.pid, 'core_pid': core.pid,
                                  'core_executable': core.exe(), 'listen_ports': ports,
                                  'established_connections': connected}), flush=True)
                shot = screenshot or root / 'window.png'
                shot.parent.mkdir(parents=True, exist_ok=True)
                time.sleep(3)  # allow the connected renderer to paint its first frame
                capture_window(window, shot.resolve())
                with Image.open(shot) as frame:
                    assert frame.width >= 500 and frame.height >= 300, 'Window capture is too small'
                    # Exclude window chrome: a created but unpainted webview is not a pass.
                    content = frame.crop((40, 100, frame.width - 40, frame.height - 40)).convert('L')
                    assert content.entropy() > 1, 'Webview screenshot is blank'
                children = psutil.Process(proc.pid).children(recursive=True)
                normal_close(window_pid, window)
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
                print('Native desktop smoke passed: rendered window, connected core, clean close', flush=True)
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
                print(log_path.read_text()[-5000:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('provide the installed desktop command after --')
    smoke(command, args.screenshot)
