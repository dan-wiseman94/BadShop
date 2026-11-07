"""The native oracle must distinguish a TCP handshake from usable renderer state."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'packaging'))
from smoke_desktop import check_native_log, renderer_is_ready


class RendererReadyTests(unittest.TestCase):
    def test_allocator_failure_cannot_hide_behind_a_clean_shell_exit(self):
        with self.assertRaisesRegex(AssertionError, 'corrupted double-linked list'):
            check_native_log('Native desktop smoke passed\ncorrupted double-linked list\n')
        check_native_log('Gtk-WARNING: Locale not supported\nMESA-EGL: warning: DRI3 error')

    def test_loading_partial_and_obsolete_observations_do_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ready.json'
            self.assertFalse(renderer_is_ready(path, 'this-run', [12345]))
            for value in ['{', '{}', '[]', json.dumps({'port': 12345, 'revision': 0}),
                          json.dumps({'port': 12344, 'session_id': 's', 'revision': 0}),
                          json.dumps({'port': 12345, 'session_id': 's', 'revision': True})]:
                path.write_text(value)
                self.assertFalse(renderer_is_ready(path, 'this-run', [12345]))
            good = {'port': 12345, 'session_id': 's', 'revision': 0, 'nonce': 'this-run', 'tool_count': 20}
            for change in ({'port': 12344}, {'revision': True}, {'nonce': 'old-run'}, {'tool_count': True}):
                path.write_text(json.dumps(good | change))
                self.assertFalse(renderer_is_ready(path, 'this-run', [12345]))
            path.write_text(json.dumps(good))
            self.assertTrue(renderer_is_ready(path, 'this-run', [12345]))
