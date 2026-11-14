"""Cross-platform installer smoke: handshake, registry, spawned find worker, EOF shutdown."""
import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import psutil
import av
from PIL import Image
from pillow_heif import register_heif_opener
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


async def smoke(executable: Path, crash: bool = False, keychain: bool = False,
                background_removal: bool = False, metrics: Path | None = None,
                cycles: int = 5, metrics_kind: str = 'packaged', capture: bool = False):
    with tempfile.TemporaryDirectory(prefix='badshop-smoke-') as folder:
        env = {**os.environ, 'BADSHOP_CONFIG_DIR': folder + '/config',
               'BADSHOP_DATA_DIR': folder + '/data', 'BADSHOP_OUT': folder + '/out',
               'BADSHOP_LOG_DIR': folder + '/logs'}
        env.pop('BADSHOP_FAKE_PROVIDER', None)
        if os.name == 'nt':
            env.setdefault('BADSHOP_SMOKE_TRACE', '1')  # set 0 to verify startup without instrumentation
        started = time.perf_counter()
        measurements = {}
        evidence = {'schema': 1, 'kind': 'core-runtime', 'platform': platform.system(),
                    'machine': platform.machine(), 'profile': f'{metrics_kind}-lifecycle-v1-{cycles}-cycles',
                    'executable': str(executable.resolve()), 'status': 'failed', 'measurements': measurements}
        proc = await asyncio.create_subprocess_exec(str(executable.resolve()), 'serve',
                                                   stdin=asyncio.subprocess.PIPE,
                                                   stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE, env=env)
        stderr = asyncio.create_task(proc.stderr.read())
        failed = False
        children = []
        def rss():
            parent = psutil.Process(proc.pid)
            return sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)])
        try:
            hello = json.loads(await asyncio.wait_for(proc.stdout.readline(), 45))
            measurements['handshake_seconds'] = time.perf_counter() - started
            assert 0 < hello['port'] < 65536 and len(hello['token']) >= 16
            async with connect(f"ws://127.0.0.1:{hello['port']}", max_size=64 * 2**20) as ws:
                await ws.send(json.dumps({'type': 'hello', 'token': hello['token'], 'actor': 'user'}))
                assert json.loads(await ws.recv())['type'] == 'welcome'
                counter = 0
                async def rpc(method, *, expected_error=None, **params):
                    nonlocal counter
                    counter += 1
                    await ws.send(json.dumps({'jsonrpc': '2.0', 'id': counter, 'method': method, 'params': params}))
                    while True:
                        # Worker startup (60s), tool execution (120s), and cleanup (5s)
                        # must finish before this harness deadline, including on cold CI hosts.
                        result = json.loads(await asyncio.wait_for(ws.recv(), 195))
                        if result.get('id') == counter:
                            if expected_error is not None:
                                error = result.get('error', {})
                                assert error.get('code') == -32000, result
                                assert expected_error in error.get('message', ''), result
                                return error
                            assert 'error' not in result, result
                            return result['result']
                tools = await rpc('tools.list')
                assert {'find', 'view', 'paste'}.issubset({t['name'] for t in tools})
                measurements['catalog_ready_seconds'] = time.perf_counter() - started
                if metrics:
                    await asyncio.sleep(.2)
                    measurements['idle_rss_bytes'] = rss()
                if keychain:
                    from smoke_keychain import exercise_keychain
                    await exercise_keychain(rpc)
                if capture:
                    before_capture = await rpc('session.get')
                    preview = await rpc('media.capture')
                    assert preview and preview['width'] > 0 and preview['height'] > 0
                    captured = await rpc('media.import', preview_id=preview['id'], candidate_ids=['0'],
                                         crop=[0, 0, 40, 30])
                    capture_id = captured['artifacts'][0]['id']
                    with Image.open(io.BytesIO(base64.b64decode((await rpc('artifacts.get', id=capture_id))['data']))) as pixels:
                        assert pixels.size == (40, 30)
                    after_capture = await rpc('session.get')
                    assert len(after_capture['artifacts']) == len(before_capture['artifacts']) + 1
                    assert after_capture['artifacts'][capture_id]['original_id'] is None
                    await rpc('media.discard', preview_id=preview['id'])
                    print('Frozen capture passed: screenshot pixels, region-only import and preview cleanup', flush=True)
                source = Path(folder) / 'input 🖼.png'
                shutil.copyfile(ROOT / 'core/tests/fixtures/lincoln.png', source)
                image = await rpc('artifacts.import', path=str(source))
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
                register_heif_opener()
                phone_path = Path(folder) / 'phone.heic'
                Image.new('RGB', (64, 32), (30, 140, 220)).save(phone_path, format='HEIF', quality=-1)
                phone = await rpc('artifacts.import', path=str(phone_path))
                assert phone['original']['format'] == 'HEIF'
                phone_frame = await rpc('artifacts.frame', id=phone['original']['id'], frame=0)
                with Image.open(io.BytesIO(base64.b64decode(phone_frame['data']))) as decoded:
                    assert decoded.size == (64, 32)
                phone_bytes = phone_path.read_bytes()
                assert base64.b64decode((await rpc('artifacts.get', id=phone['original']['id']))['data']) == phone_bytes
                pdf_path = Path(folder) / 'page.pdf'
                Image.new('RGB', (80, 60), 'blue').save(pdf_path, format='PDF')
                pdf_preview = await rpc('media.preview', path=str(pdf_path), kind='document', page=1)
                pdf_path.unlink()
                pdf_import = await rpc('media.import', preview_id=pdf_preview['id'], candidate_ids=['0'],
                                       crop=[10, 10, 30, 30])
                pdf_id = pdf_import['artifacts'][0]['id']
                pdf_bytes = (await rpc('artifacts.get', id=pdf_id))['data']
                with Image.open(io.BytesIO(base64.b64decode(pdf_bytes))) as decoded:
                    assert decoded.size == (20, 20)
                    red, green, blue = decoded.getpixel((10, 10))[:3]
                    assert red < 10 and green < 10 and blue > 240
                video_path = Path(folder) / 'clip.mp4'
                with av.open(str(video_path), 'w') as video:
                    stream = video.add_stream('mpeg4', rate=3)
                    stream.width, stream.height, stream.pix_fmt = 80, 60, 'yuv420p'
                    for color in ('red', 'green', 'blue'):
                        for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB', (80, 60), color))):
                            video.mux(packet)
                    for packet in stream.encode():
                        video.mux(packet)
                video_preview = await rpc('media.preview', path=str(video_path), kind='video', count=3)
                video_path.unlink()
                video_import = await rpc('media.import', preview_id=video_preview['id'], candidate_ids=['2'])
                video_id = video_import['artifacts'][0]['id']
                video_bytes = (await rpc('artifacts.get', id=video_id))['data']
                with Image.open(io.BytesIO(base64.b64decode(video_bytes))) as decoded:
                    assert decoded.size == (80, 60)
                    red, green, blue = decoded.getpixel((10, 10))[:3]
                    assert red < 10 and green < 10 and blue > 240
                if background_removal:
                    step = await rpc('tools.run', tool='cutout',
                                     params={'image': image['working']['id'], 'model': 'u2net'})
                    assert step['status'] == 'done' and step['outputs'], step
                    artifact = await rpc('artifacts.get', id=step['outputs'][0])
                    with Image.open(io.BytesIO(base64.b64decode(artifact['data']))) as cutout:
                        assert cutout.mode == 'RGBA' and cutout.getchannel('A').getextrema() == (0, 255)
                    print('Frozen background removal passed: U2-Net produced a transparent cutout', flush=True)
                children = psutil.Process(proc.pid).children(recursive=True)
                assert children, 'find must have started a worker'
                # Exercise the desktop's exact revision-bearing save/replacement API.
                # Startup and unguarded saves can otherwise pass against a stale core.
                snapshot = await rpc('session.get')
                assert snapshot['unsaved_changes']
                revision = snapshot['document_revision']
                await rpc('session.new', expected_revision=revision,
                          expected_error='unsaved changes')
                assert (await rpc('session.get'))['id'] == snapshot['id']
                await rpc('session.set_approval_mode', mode='ask_all')
                destination = Path(folder) / 'saved 🖼.badshop'
                await rpc('session.save_as', path=str(destination), expected_revision=revision,
                          expected_error='session changed')
                assert not destination.exists()
                snapshot = await rpc('session.get')
                saved = await rpc('session.save_as', path=str(destination),
                                  expected_revision=snapshot['document_revision'])
                assert Path(saved['path']).is_file()
                assert not (await rpc('session.get'))['unsaved_changes']
                before = destination.read_bytes()
                await rpc('session.set_approval_mode', mode='auto')
                await rpc('session.save', expected_revision=snapshot['document_revision'],
                          expected_error='session changed')
                assert destination.read_bytes() == before
                snapshot = await rpc('session.get')
                await rpc('session.save', expected_revision=snapshot['document_revision'])
                assert not (await rpc('session.get'))['unsaved_changes']
                fresh = await rpc('session.new', expected_revision=snapshot['document_revision'])
                opened = await rpc('session.open', path=str(destination),
                                   expected_revision=fresh['document_revision'])
                assert opened['id'] == snapshot['id'] and not opened['unsaved_changes']
                assert base64.b64decode((await rpc('artifacts.get', id=phone['original']['id']))['data']) == phone_bytes
                print('Frozen HEIC passed: bundled decoder, frame preview and original-byte persistence', flush=True)
                assert (await rpc('artifacts.get', id=pdf_id))['data'] == pdf_bytes
                print('Frozen PDF passed: bundled page rendering, crop and persisted pixels after source deletion', flush=True)
                assert (await rpc('artifacts.get', id=video_id))['data'] == video_bytes
                print('Frozen video passed: bundled frame extraction and persisted pixels after source deletion', flush=True)
                restored = await rpc('artifacts.get', id=image['working']['id'])
                assert hashlib.sha256(base64.b64decode(restored['data'])).hexdigest() == image['working']['id']
                # Exercise the bundled SQLite writer, not just portable ZIP Save.
                from badshop.session.recovery import load as load_recovery
                recovered = load_recovery(Path(folder) / 'data/autosave/session.sqlite')
                assert recovered.data.id == opened['id']
                assert recovered.artifacts.data(image['working']['id']) == base64.b64decode(restored['data'])
                recovered.artifacts.close()
                if metrics:
                    for cycle in range(cycles):
                        current = await rpc('session.get')
                        await rpc('session.new', expected_revision=current['document_revision'], discard_unsaved=True)
                        imported = await rpc('artifacts.import', path=str(source))
                        edited = await rpc('tools.run', tool='filter',
                                           params={'image': imported['working']['id'], 'names': ['invert']})
                        assert edited['status'] == 'done'
                        output = edited['outputs'][0]
                        current = await rpc('session.get')
                        await rpc('session.save_as', path=str(destination), expected_revision=current['document_revision'])
                        await rpc('session.new', expected_revision=current['document_revision'])
                        current = await rpc('session.get')
                        reopened = await rpc('session.open', path=str(destination), expected_revision=current['document_revision'])
                        assert reopened['steps'][0]['outputs'] == [output]
                        actual = await rpc('artifacts.get', id=output)
                        assert hashlib.sha256(base64.b64decode(actual['data'])).hexdigest() == output
                        await rpc('session.new', expected_revision=reopened['document_revision'])
                        await asyncio.sleep(.2)
                        measurements[f'cycle_{cycle + 1}_rss_bytes'] = rss()
                    measurements['retained_rss_delta_bytes'] = (
                        measurements[f'cycle_{cycles}_rss_bytes'] - measurements['cycle_1_rss_bytes'])
                    children = psutil.Process(proc.pid).children(recursive=True)
            if crash:
                proc.kill()
            else:
                proc.stdin.close()
            code = await asyncio.wait_for(proc.wait(), 15)
            assert crash or code == 0
            _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=15)
            assert not [p for p in alive if p.status() != psutil.STATUS_ZOMBIE], 'orphaned core worker'
            evidence['status'] = 'passed'
            print('Frozen core smoke passed: handshake, tools, spawned find, guarded save/open, ' +
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
                children = psutil.Process(proc.pid).children(recursive=True)
                proc.kill()
                await proc.wait()
            for child in children:
                try:
                    if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                        child.kill()
                except psutil.NoSuchProcess:
                    pass
            await asyncio.to_thread(psutil.wait_procs, children, timeout=5)
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
            if metrics:
                metrics.parent.mkdir(parents=True, exist_ok=True)
                metrics.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
                print(f'Runtime measurements: {metrics}', flush=True)


async def main(executable: Path, keychain: bool = False, background_removal: bool = False,
               metrics: Path | None = None, cycles: int = 5, metrics_kind: str = 'packaged', capture: bool = False):
    await smoke(executable, keychain=keychain, background_removal=background_removal,
                metrics=metrics, cycles=cycles, metrics_kind=metrics_kind, capture=capture)
    await smoke(executable, crash=True, capture=capture)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('executable', type=Path)
    p.add_argument('--keychain', action='store_true', help='require a real OS keychain round-trip')
    p.add_argument('--capture', action='store_true', help='capture only an isolated test display')
    p.add_argument('--background-removal', action='store_true',
                   help='download U2-Net and verify background removal in the frozen worker')
    p.add_argument('--metrics', type=Path, help='retain advisory startup/RSS evidence from repeated project cycles')
    p.add_argument('--cycles', type=int, choices=range(2, 21), default=5)
    p.add_argument('--metrics-kind', choices=('source', 'packaged'), default='packaged')
    args = p.parse_args()
    asyncio.run(main(args.executable, args.keychain, args.background_removal,
                     args.metrics, args.cycles, args.metrics_kind, args.capture))
