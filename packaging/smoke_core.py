"""Cross-platform installer smoke: handshake, registry, spawned find worker, EOF shutdown."""
import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

import psutil
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent


async def smoke(executable: Path, crash: bool = False):
    with tempfile.TemporaryDirectory(prefix='badshop-smoke-') as folder:
        env = {**os.environ, 'BADSHOP_CONFIG_DIR': folder + '/config',
               'BADSHOP_DATA_DIR': folder + '/data', 'BADSHOP_OUT': folder + '/out',
               'BADSHOP_LOG_DIR': folder + '/logs'}
        env.pop('BADSHOP_FAKE_PROVIDER', None)
        if os.name == 'nt':
            env['BADSHOP_SMOKE_TRACE'] = '1'  # independent per-PID files survive worker termination
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
                step = await rpc('tools.run', tool='find', params={'image': image['working']['id'], 'detector': 'haar'})
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
