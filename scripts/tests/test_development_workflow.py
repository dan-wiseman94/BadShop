"""Behavioral checks of task isolation, conservative CI, and safe skill updates."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from dev_context import checkout_lock, file_hash, private_ports  # noqa: E402 - standalone scripts share a sibling module
from ci_scope import classify  # noqa: E402 - standalone scripts share a sibling module
from sync_skills import NAMES, synchronize  # noqa: E402 - standalone scripts share a sibling module
from task import start, finish  # noqa: E402 - standalone scripts share a sibling module
from wsl_task import export, receive  # noqa: E402 - standalone scripts share a sibling module


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()


def repository(root):
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'user.name', 'Fixture')
    (root/'.gitignore').write_text('artifacts/\n')
    (root/'shared.txt').write_text('base')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'baseline')


class TaskTests(unittest.TestCase):
    def test_handoff_detects_upstream_and_unmerged_work_without_merging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source'
            repository(source)
            remote = root/'remote.git'
            subprocess.run(['git', 'clone', '--bare', str(source), str(remote)], check=True, capture_output=True)
            git(source, 'remote', 'add', 'origin', str(remote))
            record = source/'artifacts/context.json'
            start(source, record, ['Retain local edits'])
            peer = root/'peer'
            git(source, 'worktree', 'add', '-b', 'peer', str(peer))
            (peer/'shared.txt').write_text('peer edit')
            (source/'shared.txt').write_text('own edit')
            old_head = git(source, 'rev-parse', 'HEAD')
            publisher = root/'publisher'
            subprocess.run(['git', 'clone', str(remote), str(publisher)], check=True, capture_output=True)
            git(publisher, 'config', 'user.email', 'fixture@example.invalid')
            git(publisher, 'config', 'user.name', 'Fixture')
            (publisher/'shared.txt').write_text('upstream edit')
            git(publisher, 'commit', '-am', 'concurrent')
            git(publisher, 'push', 'origin', 'main')
            result = finish(source, record)
            self.assertTrue(result['upstream_advanced'])
            self.assertEqual(result['overlap'], ['shared.txt'])
            self.assertEqual(result['peers'][0]['overlap'], ['shared.txt'])
            self.assertEqual(git(source, 'rev-parse', 'HEAD'), old_head)
            self.assertEqual((source/'shared.txt').read_text(), 'own edit')


    def test_committing_unchanged_inherited_content_does_not_claim_it(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source'
            repository(source)
            (source/'shared.txt').write_text('inherited')
            record = source/'artifacts/context.json'
            start(source, record, ['Distinguish inherited content'])
            git(source, 'commit', '-am', 'retain inherited work')
            (source/'own.txt').write_text('task change')
            result = finish(source, record)
            self.assertEqual(result['task_paths'], ['own.txt'])

    def test_failed_fetch_does_not_claim_a_verified_tip(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source'
            repository(source)
            result = start(source, source/'artifacts/context.json', ['example'])
            self.assertFalse(result['origin_main']['verified'])


class SkillsTests(unittest.TestCase):
    def test_upgrade_preserves_local_changes_and_handles_removed_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder)/'source', Path(folder)/'installed'
            for name in NAMES:
                (source/name).mkdir(parents=True)
                (source/name/'SKILL.md').write_text('initial')
            self.assertTrue(synchronize(source, destination, apply=True))
            (destination/NAMES[0]/'SKILL.md').write_text('my edit')
            (source/NAMES[0]/'SKILL.md').write_text('upstream')
            with self.assertRaisesRegex(RuntimeError, 'installed edits'):
                synchronize(source, destination, apply=True)
            self.assertEqual((destination/NAMES[0]/'SKILL.md').read_text(), 'my edit')
            (destination/NAMES[0]/'SKILL.md').write_text('initial')
            self.assertTrue(synchronize(source, destination, apply=True))
            self.assertEqual((destination/NAMES[0]/'SKILL.md').read_text(), 'upstream')


class TransferTests(unittest.TestCase):
    def test_exact_revision_repeat_sync_and_refusal_of_linux_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source'
            repository(source)
            prefix = root/'private'
            prefix.mkdir()
            subprocess.run(['git', 'clone', '--bare', str(source), str(prefix/'repo.git')],
                           check=True, capture_output=True)
            (source/'shared.txt').write_text('windows task')
            (source/'new.txt').write_text('selected')
            archive = export(source, source/'artifacts/transfer', ['new.txt'])
            target = prefix/'worktrees/task with spaces'
            result = receive(archive, target, prefix, deps=False)
            self.assertEqual(git(target, 'rev-parse', 'HEAD'), git(source, 'rev-parse', 'HEAD'))
            self.assertEqual(file_hash(target/'shared.txt'), file_hash(source/'shared.txt'))
            self.assertNotEqual(*result['environment'].values())
            with checkout_lock(target/'artifacts/verification/.lock'):
                with self.assertRaisesRegex(RuntimeError, 'Another verification run'):
                    receive(archive, target, prefix, deps=False)
            (source/'shared.txt').write_text('followup')
            archive = export(source, source/'artifacts/transfer', ['new.txt'])
            receive(archive, target, prefix, deps=False)
            self.assertEqual((target/'shared.txt').read_text(), 'followup')
            (target/'shared.txt').write_text('linux edits')
            with self.assertRaisesRegex(RuntimeError, 'unexpected edits'):
                receive(archive, target, prefix, deps=False)
            self.assertEqual((target/'shared.txt').read_text(), 'linux edits')


class ScopeTests(unittest.TestCase):
    def test_docs_skip_expensive_jobs_but_unknown_and_shared_inputs_do_not(self):
        docs = classify(['docs/development.md', 'skills/development/example/SKILL.md'])
        self.assertFalse(any(docs[k] for k in ('core', 'frontend', 'native', 'installers')))
        self.assertTrue(classify(['future-system/config'])['installers'])
        self.assertTrue(classify(['skills/development/example/scripts/check.py'])['installers'])
        self.assertTrue(classify(['core/uv.lock'])['core'])
        self.assertTrue(classify(['app/src/App.tsx'])['installers'])
        self.assertFalse(classify(['app/e2e/example.spec.ts'])['installers'])
        self.assertTrue(classify(['README.md'], full=True)['installers'])

    def test_selected_ports_are_distinct(self):
        first, second = private_ports()
        self.assertNotEqual(first, second)


class NativeReadinessTests(unittest.TestCase):
    def test_socket_or_stale_receipt_cannot_count_as_renderer_readiness(self):
        sys.path.insert(0, str(SCRIPTS.parent/'packaging'))
        spec = importlib.util.spec_from_file_location('smoke_desktop', SCRIPTS.parent/'packaging/smoke_desktop.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder)/'ready.json'
            command = module.isolated_command(
                ['flatpak', 'run', 'app.id'], Path(folder),
                {'BADSHOP_SMOKE_READY_FILE': str(receipt), 'BADSHOP_SMOKE_NONCE': 'this-run'})
            self.assertIn(f'--filesystem={folder}', command)
            self.assertEqual(command[-1], 'app.id')
            self.assertFalse(module.renderer_is_ready(receipt, 'this-run'))
            receipt.write_text(json.dumps({'nonce': 'old-run', 'session_id': 'session', 'tool_count': 20}))
            self.assertFalse(module.renderer_is_ready(receipt, 'this-run'))
            receipt.write_text(json.dumps({'nonce': 'this-run', 'session_id': 'session', 'tool_count': 20}))
            self.assertTrue(module.renderer_is_ready(receipt, 'this-run'))
