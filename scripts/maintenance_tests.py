"""Real analyzer negative controls in disposable source trees; no application startup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from maintenance_report import ROOT, report, snapshot


class MaintenanceTests(unittest.TestCase):
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
