"""The native oracle must distinguish a TCP handshake from usable renderer state."""
import json
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'packaging'))
from smoke_desktop import check_native_log, renderer_is_ready, wait_project_pixels


class RendererReadyTests(unittest.TestCase):
    def test_project_probe_checks_pixels_and_content_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native.badshop'
            image = io.BytesIO()
            Image.new('RGBA', (40, 30), (30, 160, 240, 255)).save(image, 'PNG')
            data = image.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            state = {'id': 'owned-session', 'artifacts': {
                digest: {'format': 'PNG', 'width': 40, 'height': 30},
            }}
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('session.json', json.dumps(state))
                archive.writestr(f'artifacts/{digest}.png', data)
            self.assertEqual(wait_project_pixels(path, 'owned-session', data), state)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('session.json', json.dumps(state))
                archive.writestr(f'artifacts/{digest}.png', b'corrupt pixels')
            with self.assertRaisesRegex(AssertionError, 'artifact hash changed'):
                wait_project_pixels(path, 'owned-session', data)

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
            good = {'port': 12345, 'session_id': 's', 'revision': 0, 'nonce': 'this-run', 'tool_count': 20, 'clipboard_pixels': True}
            for change in ({'port': 12344}, {'revision': True}, {'nonce': 'old-run'}, {'tool_count': True}, {'clipboard_pixels': False}):
                path.write_text(json.dumps(good | change))
                self.assertFalse(renderer_is_ready(path, 'this-run', [12345]))
            path.write_text(json.dumps(good))
            self.assertTrue(renderer_is_ready(path, 'this-run', [12345]))
