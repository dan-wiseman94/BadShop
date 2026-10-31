"""Linux native smoke on a dedicated X server (never use the user's active display).

xvfb-run -a uv run --project core python packaging/smoke_desktop.py \
    --screenshot /tmp/badshop.png -- /path/to/installed/badshop-desktop

Requires Xvfb, xdotool, libX11 and (only for screenshots) ImageMagick. Confirms a real
renderer/core socket, a visible native window, and graceful close without child processes.
"""
import argparse
import ctypes
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import psutil


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


def smoke(command: list[str], screenshot: Path | None) -> None:
    with tempfile.TemporaryDirectory(prefix='badshop-native-smoke-') as folder:
        root = Path(folder)
        env = {**os.environ, 'GDK_BACKEND': 'x11'}
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
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f'shell exited {proc.returncode}')
                    children = psutil.Process(proc.pid).children(recursive=True)
                    cores = [p for p in children if p.name() == 'badshop-core']
                    if cores:
                        core = cores[0]
                        sockets = core.net_connections('tcp')
                        ports = [c.laddr.port for c in sockets
                                 if c.status == 'LISTEN' and c.laddr.ip == '127.0.0.1']
                        connected = [c for c in sockets if c.status == 'ESTABLISHED']
                        if ports and connected:
                            break
                    time.sleep(.2)
                else:
                    raise RuntimeError('No renderer/core connection after 45 seconds')
                print(json.dumps({'shell_pid': proc.pid, 'core_pid': core.pid,
                                  'core_executable': core.exe(), 'listen_ports': ports,
                                  'established_connections': len(connected)}), flush=True)
                windows = subprocess.check_output(
                    ['xdotool', 'search', '--onlyvisible', '--name', '^badshop$'],
                    env=env, text=True).splitlines()
                assert windows, 'No visible application window'
                if screenshot:
                    time.sleep(2)  # let the first frame settle before recording the screenshot
                    subprocess.run(['import', '-window', 'root', str(screenshot.resolve())],
                                   env=env, check=True)
                close_window(int(windows[0]))
                assert proc.wait(timeout=15) == 0, 'Native close returned a failure exit code'
                _, alive = psutil.wait_procs(children, timeout=5)
                alive = [p for p in alive if p.status() != psutil.STATUS_ZOMBIE]
                assert not alive, f'Children survived native close: {[p.pid for p in alive]}'
                print('Native desktop smoke passed: rendered window, connected core, clean close', flush=True)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                # The isolated harness owns these children; never leave them behind after a failure.
                for child in children:
                    if child.is_running():
                        child.kill()
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
