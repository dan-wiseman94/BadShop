"""Cross-platform installer smoke: handshake, registry, spawned find worker, EOF shutdown."""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psutil
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent


def windows_dialogs(pids: set[int]) -> list[dict]:
    """Read only windows owned by the smoke's process tree (including modal errors)."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user.EnumChildWindows.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowTextW.restype = ctypes.c_int
    windows = []

    def text(hwnd):
        buffer = ctypes.create_unicode_buffer(4096)
        user.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    @callback_type
    def window(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids:
            controls = []

            @callback_type
            def control(child, _):
                value = text(child)
                if value:
                    controls.append(value)
                return True

            user.EnumChildWindows(hwnd, control, 0)
            windows.append({'pid': owner.value, 'title': text(hwnd), 'controls': controls})
        return True

    user.EnumWindows(window, 0)
    return windows


def native_stack(pid: int) -> dict:
    """Bounded, noninvasive debugger attach to a worker already stalled in startup."""
    cdb = (os.environ.get('BADSHOP_CDB') or shutil.which('cdb')
           or str(Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))
                  / 'Windows Kits/10/Debuggers/x64/cdb.exe'))
    if not Path(cdb).is_file():
        return {'pid': pid, 'error': 'CDB is not installed', 'searched': cdb}
    # -pv is noninvasive; qd explicitly quits and detaches after collecting stacks.
    # -pd is incompatible with noninvasive sessions on current Windows debuggers.
    try:
        result = subprocess.run([cdb, '-pv', '-p', str(pid), '-c', '~* kb; qd'],
                                capture_output=True, timeout=20, check=False)
    except subprocess.TimeoutExpired as error:
        return {'pid': pid, 'error': 'CDB exceeded 20 seconds',
                'output': ((error.stdout or b'') + (error.stderr or b'')).decode(errors='replace')[-24000:]}
    except OSError as error:
        return {'pid': pid, 'error': type(error).__name__}
    return {'pid': pid, 'code': result.returncode,
            'output': (result.stdout + result.stderr).decode(errors='replace')[-24000:]}


def process_snapshot(pid: int, debugger: bool = False) -> dict:
    """Native bootstrap evidence, before the core startup watchdog removes its child."""
    parent = psutil.Process(pid)
    processes = [parent, *parent.children(recursive=True)]
    details = []
    for process in processes:
        item = {'pid': process.pid}
        try:
            item.update(parent=process.ppid(), exe=process.exe(), cmdline=process.cmdline(),
                        status=process.status(), rss_mb=process.memory_info().rss / 2**20,
                        cpu=process.cpu_times()._asdict(), threads=process.num_threads())
            try:
                item['modules'] = sorted({m.path for m in process.memory_maps()
                                          if m.path.lower().endswith(('.dll', '.pyd', '.exe'))})
            except psutil.Error as error:
                item['modules_error'] = type(error).__name__
        except psutil.Error as error:
            item['process_error'] = type(error).__name__
        details.append(item)
    result = {'processes': details}
    if os.name == 'nt':
        result['windows'] = windows_dialogs({p.pid for p in processes})
        workers = [item['pid'] for item in details if '--multiprocessing-fork' in item.get('cmdline', [])]
        if debugger and workers:
            result['native_stack'] = native_stack(workers[0])
    return result


async def observe_startup(pid: int):
    for delay in (1, 9):
        await asyncio.sleep(delay)
        try:
            snapshot = await asyncio.to_thread(process_snapshot, pid, delay == 9)
            print('Frozen native startup: ' + json.dumps(snapshot), flush=True)
        except (OSError, psutil.Error) as error:
            print('Frozen startup observation failed: ' + type(error).__name__, flush=True)


async def smoke(executable: Path, crash: bool = False):
    with tempfile.TemporaryDirectory(prefix='badshop-smoke-') as folder:
        env = {**os.environ, 'BADSHOP_CONFIG_DIR': folder + '/config',
               'BADSHOP_DATA_DIR': folder + '/data', 'BADSHOP_OUT': folder + '/out',
               'BADSHOP_LOG_DIR': folder + '/logs'}
        env.pop('BADSHOP_FAKE_PROVIDER', None)
        if os.name == 'nt':
            env.setdefault('BADSHOP_SMOKE_TRACE', '1')  # set 0 to verify startup without instrumentation
        proc = await asyncio.create_subprocess_exec(str(executable.resolve()), 'serve',
                                                   stdin=asyncio.subprocess.PIPE,
                                                   stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE, env=env)
        stderr = asyncio.create_task(proc.stderr.read())
        failed = False
        try:
            hello = json.loads(await asyncio.wait_for(proc.stdout.readline(), 45))
            assert 0 < hello['port'] < 65536 and len(hello['token']) >= 16
            async with connect(f"ws://127.0.0.1:{hello['port']}", max_size=64 * 2**20) as ws:
                await ws.send(json.dumps({'type': 'hello', 'token': hello['token'], 'actor': 'user'}))
                assert json.loads(await ws.recv())['type'] == 'welcome'
                counter = 0
                async def rpc(method, **params):
                    nonlocal counter
                    counter += 1
                    await ws.send(json.dumps({'jsonrpc': '2.0', 'id': counter, 'method': method, 'params': params}))
                    while True:
                        # Worker startup (60s), tool execution (120s), and cleanup (5s)
                        # must finish before this harness deadline, including on cold CI hosts.
                        result = json.loads(await asyncio.wait_for(ws.recv(), 195))
                        if result.get('id') == counter:
                            assert 'error' not in result, result
                            return result['result']
                tools = await rpc('tools.list')
                assert {'find', 'view', 'paste'}.issubset({t['name'] for t in tools})
                image = await rpc('artifacts.import', path=str(ROOT / 'core/tests/fixtures/lincoln.png'))
                # Haar requires no network and still verifies bundled OpenCV data and spawned worker.
                observer = (asyncio.create_task(observe_startup(proc.pid))
                            if env.get('BADSHOP_SMOKE_TRACE') == '1' else None)
                try:
                    step = await rpc('tools.run', tool='find',
                                     params={'image': image['working']['id'], 'detector': 'haar'})
                finally:
                    if observer:
                        observer.cancel()
                        await asyncio.gather(observer, return_exceptions=True)
                assert step['status'] == 'done', step
                saved = await rpc('session.save_as', path=str(Path(folder) / 'smoke.badshop'))
                assert Path(saved['path']).is_file()
                children = psutil.Process(proc.pid).children(recursive=True)
                assert children, 'find must have started a worker'
            if crash:
                proc.kill()
            else:
                proc.stdin.close()
            code = await asyncio.wait_for(proc.wait(), 15)
            assert crash or code == 0
            _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=15)
            assert not [p for p in alive if p.status() != psutil.STATUS_ZOMBIE], 'orphaned core worker'
            print('Frozen core smoke passed: handshake, tools, spawned find, save, ' +
                  ('forced core death' if crash else 'clean EOF exit') + ' and no orphan worker')
        except BaseException:
            failed = True
            if proc.returncode is None:
                for child in psutil.Process(proc.pid).children(recursive=True):
                    try:
                        print(json.dumps({'child_pid': child.pid, 'name': child.name(),
                                          'status': child.status(), 'rss_mb': child.memory_info().rss / 2**20}))
                    except psutil.Error:
                        pass
            raise
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            errors = (await stderr).decode(errors='replace')
            if failed or (proc.returncode and not crash):
                print(errors[-8000:])
                # The failing startup watchdog may already have killed the child. Its
                # private descriptor still leaves a trace even when stderr was not inherited.
                for trace in sorted((Path(folder) / 'logs').glob('frozen-*.trace.log')):
                    print(f'--- frozen process trace: {trace.name} ---')
                    try:
                        print(trace.read_text(encoding='utf-8', errors='replace')[-16000:])
                    except OSError as error:
                        print(f'could not read frozen trace: {type(error).__name__}')


async def main(executable: Path):
    await smoke(executable)
    await smoke(executable, crash=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('executable', type=Path)
    asyncio.run(main(p.parse_args().executable))
