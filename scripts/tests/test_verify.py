"""Contract checks for reporting failures and cleaning up verification processes."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psutil

SCRIPT = Path(__file__).resolve().parents[1] / 'verify.py'
spec = importlib.util.spec_from_file_location('verify', SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerificationTests(unittest.TestCase):
    def test_runs_the_resolved_package_manager_including_its_windows_suffix(self):
        with patch.object(verify.shutil, 'which', return_value=r'C:\Program Files\nodejs\pnpm.cmd'):
            self.assertEqual(verify.package_manager(), [r'C:\Program Files\nodejs\pnpm.cmd'])

    def test_concurrent_runs_cannot_share_a_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'verify.lock'
            code = ('from pathlib import Path; from scripts.verify import checkout_lock; '
                    f'checkout_lock(Path({str(lock)!r})).__enter__()')
            with verify.checkout_lock(lock):
                result = subprocess.run([sys.executable, '-c', code], cwd=verify.ROOT,
                                        capture_output=True, text=True, check=False, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Another verification run', result.stderr)
            with verify.checkout_lock(lock):
                pass  # The OS releases the lock when the owning run exits.

    def test_failure_is_retained_and_never_reported_as_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = verify.Checks(Path(directory))
            self.assertFalse(checks.run('broken', [sys.executable, '-c',
                'print("useful failure detail"); raise SystemExit(7)']))
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            self.assertEqual(summary['checks'][0]['status'], 'failed')
            self.assertEqual(summary['checks'][0]['exit_code'], 7)
            self.assertIn('useful failure detail', (Path(directory) / 'broken.log').read_text())

    def test_missing_executable_is_a_failure_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = verify.Checks(Path(directory))
            self.assertFalse(checks.run('missing', [str(Path(directory) / 'absent')]))
            self.assertIsNone(checks.results[0]['exit_code'])
            self.assertTrue(checks.results[0]['error'])

    def test_timeout_kills_owned_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile = root / 'child.pid'
            code = ('import subprocess, sys, time; from pathlib import Path; '
                    'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); '
                    f'Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)')
            checks = verify.Checks(root)
            self.assertFalse(checks.run('timeout', [sys.executable, '-c', code], timeout=2))
            self.assertIn('Timed out', checks.results[0]['error'])
            pid = int(pidfile.read_text())
            try:
                self.assertEqual(psutil.Process(pid).status(), psutil.STATUS_ZOMBIE)
            except psutil.NoSuchProcess:
                pass

    def test_help_does_not_start_checks(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn('doctor', result.stdout)

    def test_rejects_options_that_would_narrow_or_skip_full_checks(self):
        for args in (['all', '--browser-test', 'controller'],
                     ['browser', '--browser-test=--pass-with-no-tests'],
                     ['quick', '--browser-workers', '2'],
                     ['desktop', '--core-workers', '1'],
                     ['quick', '--core-workers', '0']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(SCRIPT), *args],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Evidence:', result.stdout)

    def test_no_mode_shows_help_without_starting_verification(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('Evidence:', result.stdout)

    def test_focused_python_retains_evidence_and_rejects_zero_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'scripts').mkdir()
            shutil.copy2(SCRIPT, root/'scripts/verify.py')
            shutil.copy2(SCRIPT.with_name('dev_context.py'), root/'scripts/dev_context.py')
            subprocess.run(['git', 'init', '-b', 'main', str(root)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(root), 'add', 'scripts'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline'],
                           check=True, capture_output=True)
            fixture = root / 'test_selected.py'
            fixture.write_text('def test_real_output(tmp_path):\n    p = tmp_path / "result"\n    p.write_bytes(b"output")\n    assert p.read_bytes() == b"output"\n')
            output = root / 'evidence'
            command = [sys.executable, str(root/'scripts/verify.py'), 'python', '--python-test',
                       str(fixture) + '::test_real_output', '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((output/'summary.json').read_text())
            self.assertEqual(summary['checks'][-1]['executed'], 1)
            self.assertTrue(summary['source']['fingerprint'])
            command[4] = str(fixture) + '::missing_test'
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            summary = json.loads((output/'summary.json').read_text())
            self.assertTrue(any(x['status'] == 'failed' for x in summary['checks']))


if __name__ == '__main__':
    unittest.main()
