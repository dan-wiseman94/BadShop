"""Real analyzer negative controls in disposable source trees; no application startup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import maintenance_report
from maintenance_report import ROOT, report, review_note, safeguard_changes, safeguards_report, snapshot


class MaintenanceTests(unittest.TestCase):
    def test_safeguard_report_detects_changed_oracles_selection_and_removed_assertions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
            git('init')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            files = {'core/tests/fixtures/golden.json': '{}', '.importlinter': 'guard',
                     'core/tests/test_guard.py': 'def test_guard():\n    assert result == expected\n',
                     '.github/workflows/core.yml': 'required check', 'core/src/a.py': 'print(1)\n'}
            for path, content in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            git('add', '.')
            git('commit', '-m', 'baseline')
            self.assertEqual(safeguard_changes(root, 'HEAD', None), [])
            for path in files:
                (root / path).write_text('changed\n')
            signals = dict(safeguard_changes(root, 'HEAD', None))
            self.assertEqual(set(signals), set(files) - {'core/src/a.py'})
            self.assertIn('Assertions removed', signals['core/tests/test_guard.py'])
            (root / 'core/tests/test_new.py').write_text('@pytest.mark.skip\ndef test_new(): pass\n')
            self.assertIn('core/tests/test_new.py', dict(safeguard_changes(root, 'HEAD', None)))
            self.assertIn('not findings', safeguards_report(list(signals.items())))
            git('add', '.')
            git('commit', '-m', 'candidate')
            self.assertEqual(dict(safeguard_changes(root, 'HEAD^', 'HEAD'))['.importlinter'], signals['.importlinter'])

    def test_safeguard_explanation_ignores_template_comments_and_empty_answers(self):
        for body in ('', '## Safeguard changes\n<!-- explain -->\n', '## Safeguard changes\nNone\n## Validation\npassed'):
            self.assertEqual(review_note(body), '')
        self.assertEqual(review_note('## Safeguard changes\nUpdated encoder hashes; pixel hashes still checked.\n## Validation\npassed'),
                         'Updated encoder hashes; pixel hashes still checked.')

    def test_pr_gate_retains_report_before_refusing_an_unexplained_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for args in (['init'], ['config', 'user.name', 'Fixture'],
                         ['config', 'user.email', 'fixture@example.invalid']):
                subprocess.run(['git', '-C', folder, *args], check=True, capture_output=True)
            guard = root / '.importlinter'
            guard.write_text('original guard')
            subprocess.run(['git', '-C', folder, 'add', '.'], check=True, capture_output=True)
            subprocess.run(['git', '-C', folder, 'commit', '-m', 'base'], check=True, capture_output=True)
            guard.write_text('changed guard')
            event, output = root / 'event.json', root / 'report.md'
            event.write_text(json.dumps({'pull_request': {'body': '## Safeguard changes\nNone'}}))
            arguments = ['report', '--base', 'HEAD', '--review-event', str(event), '--output', str(output)]
            with patch.object(maintenance_report, 'ROOT', root), patch('sys.argv', arguments):
                with self.assertRaisesRegex(SystemExit, 'Explain flagged changes'):
                    maintenance_report.main()
                self.assertIn('.importlinter', output.read_text(encoding='utf-8'))
                event.write_text(json.dumps({'pull_request': {'body': '## Safeguard changes\nNarrow false positive; negative control retained.'}}))
                maintenance_report.main()

    def run_tool(self, args, cwd, **env):
        return subprocess.run(args, cwd=cwd, env=os.environ | env, capture_output=True, text=True)

    def test_import_contract_detects_engine_to_session_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT / 'core/src/badshop', root / 'badshop', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copyfile(ROOT / '.importlinter', root / '.importlinter')
            args = ['lint-imports', '--no-cache']
            result = self.run_tool(args, root, PYTHONPATH=str(root))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (root / 'badshop/engine/maintenance_probe.py').write_text('from ..session import session\n')
            result = self.run_tool(args, root, PYTHONPATH=str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Engine cannot depend on application layers BROKEN', result.stdout)

    def test_ruff_detects_aliased_execution_bypass_but_allows_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for owner in ('server', 'session'):
                source = root / 'src/badshop' / owner / 'probe.py'
                source.parent.mkdir(parents=True)
                source.write_text('from badshop.tools import runner as r\nr.execute(None)\n')
                result = self.run_tool(['ruff', 'check', '--config', str(ROOT / 'core/pyproject.toml'),
                                        '--select', 'TID251', str(source)], root)
                self.assertEqual(result.returncode, 1 if owner == 'server' else 0, result.stdout + result.stderr)
                if owner == 'server':
                    self.assertIn('TID251', result.stdout)

    def test_ruff_allows_direct_runner_calls_in_core_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'core/tests/test_runner.py'
            source.parent.mkdir(parents=True)
            source.write_text('from badshop.tools.runner import run_tool\nrun_tool(None)\n')
            result = self.run_tool(['ruff', 'check', '--config', str(ROOT / 'core/pyproject.toml'),
                                    '--select', 'TID251', str(source)], root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_vulture_detects_unreachable_code(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'probe.py'
            source.write_text('def probe():\n    return 1\n    print("unreachable")\n\nprobe()\n')
            result = self.run_tool(['vulture', str(source), '--min-confidence', '100'], folder)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('unreachable', result.stdout)

    def test_knip_detects_unused_file_dependency_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'package.json').write_text(json.dumps({'name': 'maintenance-fixture', 'private': True,
                'dependencies': {'unused-fixture-package': '*'}}))
            (root / 'knip.json').write_text(json.dumps({'entry': ['index.ts'], 'project': ['*.ts']}))
            (root / 'index.ts').write_text('import { used } from "./used"; console.log(used);\n')
            (root / 'used.ts').write_text('export const used = 1; export const abandoned = 2;\n')
            (root / 'orphan.ts').write_text('export const orphan = 3;\n')
            result = self.run_tool(['node', str(ROOT / 'app/node_modules/knip/bin/knip.js'),
                                    '--reporter', 'json'], root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            findings = json.loads(result.stdout)
            self.assertIn('orphan.ts', json.dumps(findings))
            self.assertIn('unused-fixture-package', json.dumps(findings))
            self.assertIn('abandoned', json.dumps(findings))

    def test_report_tracks_deletions_complexity_and_dependency_changes(self):
        before = {'core/src/a.py': 'def choose(x):\n    return x\n', 'app/src/old.ts': 'export const a = 1;\n',
                  'app/package.json': '{"dependencies":{"old":"1"}}'}
        after = {'core/src/a.py': 'def choose(x):\n    if x:\n        return 1\n    return 0\n',
                 'app/src/new.ts': 'export function choose(x: boolean) { if(x) return 1; return 0; }\n',
                 'app/package.json': '{"dependencies":{"new":"2"}}'}
        text = report(before, after)
        self.assertIn('| `app/src/old.ts` | 1 | 0 | -1 |', text)
        self.assertIn('1 → 2', text)
        self.assertIn('app/src/new.ts', text)
        self.assertIn('0 → 2', text)
        self.assertIn('removed', text)
        self.assertIn('dependencies:new', text)

    def test_snapshot_compares_git_base_with_untracked_and_deleted_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
            git('init')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            source = root / 'core/src/a.py'
            source.parent.mkdir(parents=True)
            source.write_text('print(1)\n')
            git('add', '.')
            git('commit', '-m', 'baseline')
            source.unlink()
            (source.parent / 'new.py').write_text('print(2)\n')
            self.assertEqual(set(snapshot(root, 'HEAD')), {'core/src/a.py'})
            self.assertEqual(set(snapshot(root, None)), {'core/src/new.py'})


if __name__ == '__main__':
    unittest.main()
