"""Generated schema drift and resource-report failures must remain visible."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import create_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate_wire_types as wire
from resource_report import comparison, history_workload, sizes


class EvidenceTests(unittest.TestCase):
    def test_history_workload_records_real_roundtrip_and_archive_limit_failures(self):
        report = history_workload(4, 2)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(report['raw']['edit_seconds']), 4)
        self.assertEqual(len(report['raw']['checkpoint_seconds']), 2)
        self.assertGreater(report['measurements']['archive_bytes'], 0)
        from badshop.session import project
        with patch.object(project, 'MAX_SESSION_BYTES', 10):
            failed = history_workload(1, 0)
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('over', failed['error'])
        self.assertNotIn('archive_bytes', failed['measurements'])

    def test_wire_check_rejects_schema_drift_and_regeneration_restores_it(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'wire.ts'
            destination.write_text(wire.generate(), encoding='utf-8')
            changed = create_model('Step', __base__=wire.Step, new_required_field=(str, ...))
            with patch.object(wire, 'DESTINATION', destination), patch.object(sys, 'argv', ['generate', '--check']):
                self.assertEqual(wire.main(), 0)
                with patch.object(wire, 'Step', changed), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(wire.main(), 1)
                    self.assertIn('new_required_field', output.getvalue())
                    destination.write_text(wire.generate(), encoding='utf-8')
                    self.assertEqual(wire.main(), 0)

    def test_wire_nullability_and_unknown_schema_are_not_silently_erased(self):
        self.assertEqual(wire.ts_type({'anyOf': [{'type': 'string'}, {'type': 'null'}]}), 'string | null')
        with self.assertRaisesRegex(ValueError, 'Unsupported wire schema'):
            wire.ts_type({'oneOf': [{'type': 'string'}]})

    def test_sizes_measure_actual_bytes_and_refuse_missing_builds(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, 'missing'):
                sizes(root, 'frontend')
            dist = root / 'app/dist'
            dist.mkdir(parents=True)
            (dist / 'index.html').write_bytes(b'html')
            (dist / 'app.js').write_bytes(b'x' * 200)
            (dist / 'style.css').write_bytes(b'css')
            result = sizes(root, 'frontend')
            self.assertEqual(result['total_bytes'], 207)
            self.assertEqual(result['javascript_bytes'], 200)
            self.assertLess(result['javascript_gzip_bytes'], 200)
            with self.assertRaisesRegex(ValueError, 'No packaged installers'):
                sizes(root, 'packages')
            installer = root / 'app/src-tauri/target/release/bundle/nsis/app.exe'
            installer.parent.mkdir(parents=True)
            installer.write_bytes(b'installer')
            core = root / 'packaging/core-dist/badshop-core'
            core.mkdir(parents=True)
            (core / 'runtime').write_bytes(b'12345')
            result = sizes(root, 'packages')
            self.assertEqual(result['unpacked_core_bytes'], 5)
            self.assertEqual(result['installer_exe_bytes'], 9)
            installer.rename(installer.with_name('app-next-version.exe'))
            self.assertEqual(sizes(root, 'packages'), result)
            installer.write_bytes(b'ambiguous')
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                sizes(root, 'packages')

    def test_comparison_requires_matching_measurement_profile(self):
        report = {'schema': 1, 'kind': 'frontend', 'profile': 'production-build-v1',
                  'platform': 'Linux', 'machine': 'x86_64', 'measurements': {'total_bytes': 200}}
        self.assertIn('+100.00', comparison(report, report | {'measurements': {'total_bytes': 100}}))
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            comparison(report, report | {'platform': 'Windows'})
        with self.assertRaisesRegex(ValueError, 'Failed measurements'):
            comparison(report, report | {'status': 'failed'})


if __name__ == '__main__':
    unittest.main()
