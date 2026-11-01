"""Contract checks for reporting failures and cleaning up verification processes."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import psutil

SCRIPT = Path(__file__).resolve().parents[1] / 'verify.py'
spec = importlib.util.spec_from_file_location('verify', SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerificationTests(unittest.TestCase):
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
            self.assertIn('No such file', checks.results[0]['error'])

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


if __name__ == '__main__':
    unittest.main()
