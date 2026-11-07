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
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev_context import snapshot, private_ports, checkout_lock

ROOT = Path(__file__).resolve().parents[1]
MODES = ('python', 'component', 'quick', 'browser', 'desktop', 'all', 'doctor')


def package_manager() -> list[str]:
    if pnpm := shutil.which('pnpm'):
        return [pnpm]
    if corepack := shutil.which('corepack'):
        return [corepack, 'pnpm@10']
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
        try:
            self.source.update(snapshot(ROOT))
        except (OSError, subprocess.SubprocessError):
            self.source['fingerprint'] = None
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
    required = ['uv', 'node', 'npm', 'cargo', 'rustc']
    if sys.platform == 'linux':
        required += ['pkg-config', 'Xvfb', 'xvfb-run', 'xauth', 'xdotool', 'import', 'dbus-run-session']
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


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected a positive integer') from exc
    if result < 1:
        raise argparse.ArgumentTypeError('expected a positive integer')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=MODES, nargs='?', default=None,
                        help='Select focused python/component/browser or an explicit broad mode')
    parser.add_argument('--output', type=Path, help='Evidence directory (default: artifacts/verification/<run>)')
    parser.add_argument('--core-workers', type=positive_int,
                        help='Python test workers for quick or all (default: 1)')
    parser.add_argument('--browser-workers', type=positive_int,
                        help='Override the Playwright worker count for browser or all')
    parser.add_argument('--browser-test', action='append', default=[],
                        help='Playwright file pattern for a focused browser run (repeatable)')
    parser.add_argument('--python-test', action='append', default=[], help='Exact pytest file or node ID')
    parser.add_argument('--component-test', action='append', default=[], help='Vitest file filter')
    parser.add_argument('--test-name', help='Vitest title or Playwright grep expression')
    args = parser.parse_args()
    if args.mode is None:
        parser.print_help()
        return 0
    for field, mode in [('python_test', 'python'), ('component_test', 'component')]:
        values = getattr(args, field)
        if values and args.mode != mode:
            parser.error(f'--{field.replace("_", "-")} requires {mode}')
        if args.mode == mode and not values:
            parser.error(f'{mode} requires an explicit test selection')
        if any(not value.strip() or value.startswith('-') for value in values):
            parser.error('Test selectors must be nonempty and cannot be options')
    if args.test_name is not None and (not args.test_name.strip() or args.mode not in ('component', 'browser')):
        parser.error('--test-name requires component or browser and a nonempty pattern')
    if args.test_name and args.mode == 'browser' and not args.browser_test:
        parser.error('--test-name requires --browser-test')
    if args.core_workers is not None and args.mode not in ('quick', 'all'):
        parser.error('--core-workers requires quick or all')
    if args.browser_workers is not None and args.mode not in ('browser', 'all'):
        parser.error('--browser-workers requires browser or all')
    if args.browser_test and args.mode != 'browser':
        parser.error('--browser-test requires browser')
    if any(not pattern.strip() or pattern.startswith('-') for pattern in args.browser_test):
        parser.error('--browser-test takes a file pattern, not a Playwright option')
    try:
        with checkout_lock(ROOT / 'artifacts/verification/.lock'):
            return verify(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def focused(args: argparse.Namespace, checks: Checks, manager: list[str], env: dict) -> int:
    report = checks.output / ('tests.xml' if args.mode == 'python' else 'tests.json')
    # Reusing an explicit output directory must not accept a stale test report.
    report.unlink(missing_ok=True)
    if args.mode == 'python':
        command = [sys.executable, '-m', 'pytest', *args.python_test, '-q', '-ra',
                   '-m', 'not models and not network and not live', f'--junitxml={report}']
    elif args.mode == 'component':
        command = [*manager, '--dir', 'app', 'exec', 'vitest', 'run', *args.component_test,
                   '--reporter=default', '--reporter=json', f'--outputFile={report}']
        if args.test_name:
            command += ['-t', args.test_name]
    else:
        env = env | {'CI': '1', 'PLAYWRIGHT_JSON_OUTPUT_NAME': str(report)}
        command = [*manager, '--dir', 'app', 'exec', 'playwright', 'test', *args.browser_test,
                   '--reporter=list,json', '--output', str(checks.output / 'browser')]
        if args.test_name:
            command += ['--grep', args.test_name]
        if args.browser_workers:
            command += ['--workers', str(args.browser_workers)]
    passed = checks.run(f'{args.mode}-focused', command, env=env, timeout=1800)
    try:
        if args.mode == 'python':
            suites = ET.parse(report).getroot().iter('testsuite')
            counts = list(suites)
            skipped = sum(int(x.get('skipped', 0)) for x in counts)
            executed = sum(int(x.get('tests', 0)) for x in counts) - skipped
        else:
            data = json.loads(report.read_text())
            if args.mode == 'component':
                executed = data.get('numPassedTests', 0) + data.get('numFailedTests', 0)
                skipped = data.get('numPendingTests', 0) + data.get('numTodoTests', 0)
            else:
                stats = data.get('stats', {})
                executed = sum(stats.get(x, 0) for x in ('expected', 'unexpected', 'flaky'))
                skipped = stats.get('skipped', 0)
        selected = checks.record('test-selection', 'passed' if executed else 'failed',
                                 executed=executed, skipped=skipped,
                                 reason=None if executed else 'No tests executed; check the selector')
    except (OSError, ValueError, ET.ParseError) as exc:
        selected = checks.record('test-selection', 'failed', reason=f'Missing/invalid test report: {exc}')
    return 0 if passed and selected else 1


def verify(args: argparse.Namespace) -> int:
    output = args.output or ROOT / 'artifacts/verification' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}')
    checks = Checks(output.resolve())
    print(f'Evidence: {checks.output}', flush=True)
    try:
        if args.mode == 'doctor':
            return 0 if doctor(checks) else 1
        manager = package_manager() if args.mode != 'python' else []
        python = [sys.executable]
        env = dict(os.environ)
        # Let the test fixtures select their own app folders rather than inherit user overrides.
        for name in ('BADSHOP_DATA_DIR', 'BADSHOP_CONFIG_DIR', 'BADSHOP_LOG_DIR',
                     'BADSHOP_OUT', 'BADSHOP_FAKE_PROVIDER'):
            env.pop(name, None)
        # Each checkout builds its own binary; ambient Cargo overrides must not select another app.
        env['CARGO_TARGET_DIR'] = str(ROOT / 'app/src-tauri/target')
        env.pop('CARGO_BUILD_TARGET', None)
        browser_port, dev_port = private_ports()
        env.setdefault('BADSHOP_E2E_PORT', str(browser_port))
        env.setdefault('BADSHOP_DEV_PORT', str(dev_port))
        env['BADSHOP_UV'] = shutil.which('uv') or 'uv'
        # No PyInstaller bundle is needed: debug shell startup uses this checkout's uv project.
        env['TAURI_CONFIG'] = json.dumps({'bundle': {'resources': []}})
        if args.mode != 'python' and not checks.run('frontend-dependencies', [*manager, '--dir', 'app', 'install', '--frozen-lockfile'], env=env):
            return 1
        if args.mode in ('python', 'component') or (args.mode == 'browser' and args.browser_test):
            return focused(args, checks, manager, env)
        built = False
        if args.mode in ('quick', 'all'):
            checks.run('core-lint', [*python, '-m', 'ruff', 'check', '--config', 'core/pyproject.toml',
                                   'core', 'scripts', 'packaging/smoke_desktop.py'], env=env)
            checks.run('workflow-tests', [*python, '-m', 'unittest', 'discover', '-s', 'scripts/tests'], env=env)
            core_command = [*python, '-m', 'pytest', 'core/tests', '-q', '-ra', '-m',
                            'not models and not network and not live']
            if args.core_workers and args.core_workers > 1:
                core_command.extend(['-n', str(args.core_workers), '--dist', 'loadfile'])
            checks.run('core-tests', core_command, env=env)
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
            browser_env = env | {'CI': '1', 'BADSHOP_E2E_PORT': env['BADSHOP_E2E_PORT']}
            name = 'browser-focused' if args.browser_test else 'browser-tests'
            if built:
                browser_command = [*manager, '--dir', 'app', 'exec', 'playwright', 'test',
                                   '--output', str(checks.output / 'browser')]
                if args.browser_workers is not None:
                    browser_command.extend(['--workers', str(args.browser_workers)])
                browser_command.extend(args.browser_test)
                checks.run(name, browser_command, env=browser_env, timeout=1800)
            else:
                checks.record(name, 'blocked', reason='Frontend build failed')
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
                    launcher_env = env | {'BADSHOP_DEV_PORT': env['BADSHOP_DEV_PORT']}
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
