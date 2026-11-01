"""Repeatable local checks with retained evidence; no provider calls or model downloads."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
MODES = ('quick', 'browser', 'desktop', 'all', 'doctor')


@contextmanager
def checkout_lock(path: Path):
    """Do not let two runs rebuild the same frontend or native binary concurrently."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as lock:
        try:
            if os.name == 'nt':
                import msvcrt
                if path.stat().st_size == 0:
                    lock.write('0')
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another verification run owns this checkout; wait for it or use another worktree.') from exc
        yield


def package_manager() -> list[str]:
    if shutil.which('pnpm'):
        return ['pnpm']
    if shutil.which('corepack'):
        return ['corepack', 'pnpm@10']
    raise RuntimeError('Install pnpm 10 or Corepack; see docs/development.md.')


def stop_process(proc: subprocess.Popen) -> None:
    """Stop only the process tree owned by this check, including on interruption."""
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    if os.name == 'posix':
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(children, timeout=3)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=3)
    if os.name == 'posix':
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class Checks:
    def __init__(self, output: Path):
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.results: list[dict] = []
        self.source = {}
        for key, command in [('revision', ['git', 'rev-parse', 'HEAD']),
                             ('working_tree', ['git', 'status', '--short'])]:
            try:
                self.source[key] = subprocess.check_output(command, cwd=ROOT, text=True, timeout=10).strip()
            except (subprocess.SubprocessError, OSError):
                self.source[key] = 'unavailable'

    def record(self, name: str, status: str, **detail) -> bool:
        self.results.append({'name': name, 'status': status, **detail})
        (self.output / 'summary.json').write_text(json.dumps({
            'root': str(ROOT), 'source': self.source, 'checks': self.results,
        }, indent=2) + '\n')
        print(f'{status.upper()}: {name}', flush=True)
        return status == 'passed'

    def run(self, name: str, command: list[str], *, env: dict | None = None,
            timeout: float = 900) -> bool:
        log_path = self.output / f'{name}.log'
        print(f'\nRunning {name}; log: {log_path}', flush=True)
        start = time.monotonic()
        code, error = None, None
        with log_path.open('w') as log:
            log.write(f'cwd: {ROOT}\ncommand: {json.dumps(command)}\n\n')
            log.flush()
            try:
                proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, start_new_session=os.name == 'posix')
                try:
                    code = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    error = f'Timed out after {timeout}s'
                except KeyboardInterrupt:
                    self.record(name, 'interrupted', log=str(log_path))
                    raise
                finally:
                    stop_process(proc)
            except OSError as exc:
                error = str(exc)
        if error:
            with log_path.open('a') as log:
                log.write(f'\n{error}\n')
        passed = self.record(name, 'passed' if code == 0 and not error else 'failed',
                             exit_code=code, error=error, seconds=round(time.monotonic() - start, 2),
                             log=str(log_path))
        print('\n'.join(log_path.read_text(errors='replace').splitlines()[-18:]), flush=True)
        return passed


def doctor(checks: Checks) -> bool:
    required = ['uv', 'node', 'npm', 'cargo', 'rustc', 'pkg-config']
    if sys.platform == 'linux':
        required += ['Xvfb', 'xvfb-run', 'xauth', 'xdotool', 'import', 'dbus-run-session']
    paths = {name: shutil.which(name) for name in required}
    try:
        manager = package_manager()
    except RuntimeError:
        manager = None
    print(json.dumps({'tools': paths, 'package_manager': manager}, indent=2))
    good = checks.record('prerequisites', 'passed' if all(paths.values()) and manager else 'failed',
                         tools=paths, package_manager=manager)
    if sys.platform == 'linux':
        good = checks.run('native-libraries', ['pkg-config', '--modversion',
                                             'gtk+-3.0', 'webkit2gtk-4.1', 'openssl']) and good
    return good


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=MODES, nargs='?', default='quick',
                        help='quick (default), browser, desktop (Linux Xvfb), all, or doctor')
    parser.add_argument('--output', type=Path, help='Evidence directory (default: artifacts/verification/<run>)')
    args = parser.parse_args()
    try:
        with checkout_lock(ROOT / 'artifacts/verification/.lock'):
            return verify(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def verify(args: argparse.Namespace) -> int:
    output = args.output or ROOT / 'artifacts/verification' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}')
    checks = Checks(output.resolve())
    print(f'Evidence: {checks.output}', flush=True)
    try:
        if args.mode == 'doctor':
            return 0 if doctor(checks) else 1
        manager = package_manager()
        python = [sys.executable]
        env = dict(os.environ)
        # Let the test fixtures select their own app folders rather than inherit user overrides.
        for name in ('BADSHOP_DATA_DIR', 'BADSHOP_CONFIG_DIR', 'BADSHOP_LOG_DIR',
                     'BADSHOP_OUT', 'BADSHOP_FAKE_PROVIDER'):
            env.pop(name, None)
        # Each checkout builds its own binary; ambient Cargo overrides must not select another app.
        env['CARGO_TARGET_DIR'] = str(ROOT / 'app/src-tauri/target')
        env.pop('CARGO_BUILD_TARGET', None)
        env['BADSHOP_UV'] = shutil.which('uv') or 'uv'
        # No PyInstaller bundle is needed: debug shell startup uses this checkout's uv project.
        env['TAURI_CONFIG'] = json.dumps({'bundle': {'resources': []}})
        if not checks.run('frontend-dependencies', [*manager, '--dir', 'app', 'install', '--frozen-lockfile'], env=env):
            return 1
        built = False
        if args.mode in ('quick', 'all'):
            checks.run('core-lint', [*python, '-m', 'ruff', 'check', '--config', 'core/pyproject.toml',
                                   'core', 'scripts', 'packaging/smoke_desktop.py'], env=env)
            checks.run('workflow-tests', [*python, '-m', 'unittest', 'discover', '-s', 'scripts/tests'], env=env)
            checks.run('core-tests', [*python, '-m', 'pytest', 'core/tests', '-q', '-ra', '-m',
                                     'not models and not network and not live'], env=env)
            checks.run('frontend-tests', [*manager, '--dir', 'app', 'test'], env=env)
            built = checks.run('frontend-build', [*manager, '--dir', 'app', 'build'], env=env)
            checks.run('rust-format', ['cargo', 'fmt', '--manifest-path', 'app/src-tauri/Cargo.toml', '--', '--check'], env=env)
            if built:
                checks.run('rust-tests', ['cargo', 'test', '--manifest-path', 'app/src-tauri/Cargo.toml', '--locked'],
                           env=env, timeout=1800)
            else:
                checks.record('rust-tests', 'blocked', reason='Frontend build failed')
        if args.mode in ('browser', 'all'):
            if args.mode == 'browser':
                built = checks.run('frontend-build', [*manager, '--dir', 'app', 'build'], env=env)
            # CI disables reuse of an unrelated dev server. A dedicated port permits the normal app to stay open.
            browser_env = env | {'CI': '1', 'BADSHOP_E2E_PORT': os.environ.get('BADSHOP_E2E_PORT', '1421')}
            if built:
                checks.run('browser-tests', [*manager, '--dir', 'app', 'exec', 'playwright', 'test',
                                            '--output', str(checks.output / 'browser')], env=browser_env, timeout=1800)
            else:
                checks.record('browser-tests', 'blocked', reason='Frontend build failed')
        if args.mode in ('desktop', 'all'):
            if sys.platform != 'linux':
                checks.record('native-desktop', 'blocked', reason='Local private-display runner supports Linux; see native CI for macOS/Windows')
            elif doctor(checks):
                # XDG isolation in the native harness must not relocate pnpm's dependency store.
                try:
                    env['npm_config_store_dir'] = subprocess.check_output(
                        [*manager, '--dir', 'app', 'store', 'path'], cwd=ROOT, env=env,
                        text=True, timeout=30).strip()
                except (subprocess.SubprocessError, OSError) as exc:
                    raise RuntimeError(f'Could not resolve the pnpm store: {exc}') from exc
                built = checks.run('desktop-build', [*manager, '--dir', 'app', 'tauri', 'build', '--debug',
                                                     '--no-bundle', '--config', env['TAURI_CONFIG'], '--', '--locked'],
                                   env=env, timeout=1800)
                if built:
                    checks.run('native-desktop', ['dbus-run-session', '--', 'xvfb-run', '-a',
                               '--server-args=-screen 0 1600x1100x24', *python, 'packaging/smoke_desktop.py',
                               '--screenshot', str(checks.output / 'native.png'), '--',
                               str(ROOT / 'app/src-tauri/target/debug/badshop-desktop')], env=env, timeout=180)
                    launcher_env = env | {'BADSHOP_DEV_PORT': os.environ.get('BADSHOP_DEV_PORT', '1422')}
                    checks.run('launcher-desktop', ['dbus-run-session', '--', 'xvfb-run', '-a',
                               '--server-args=-screen 0 1600x1100x24', *python, 'packaging/smoke_desktop.py',
                               '--startup-timeout', '900', '--screenshot', str(checks.output / 'launcher.png'),
                               '--', str(ROOT / 'start.sh')], env=launcher_env, timeout=1020)
                else:
                    checks.record('native-desktop', 'blocked', reason='Desktop build failed')
            else:
                checks.record('native-desktop', 'blocked', reason='Missing native prerequisites; see docs/development.md')
        return 0 if all(result['status'] == 'passed' for result in checks.results) else 1
    except (RuntimeError, KeyboardInterrupt) as exc:
        checks.record('verification', 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', reason=str(exc))
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        print(f'\nResults: {checks.output / "summary.json"}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
