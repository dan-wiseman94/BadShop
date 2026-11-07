"""Record task baselines and report concurrent work; never merge or reset."""
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path
from dev_context import changed_paths, file_hash, git, snapshot, write_json

ROOT = Path(__file__).resolve().parents[1]


def remote_tip(root: Path) -> dict:
    result = subprocess.run(['git', '-C', str(root), 'fetch', 'origin', 'main'],
                            capture_output=True, text=True)
    if result.returncode:
        return {'verified': False, 'error': 'Fetch failed; remote tip is unverified.'}
    return {'verified': True, 'commit': git(root, 'rev-parse', 'origin/main')}


def peers(root: Path, own_paths: set[str]) -> list[dict]:
    raw = git(root, 'worktree', 'list', '--porcelain', '-z')
    result = []
    for block in raw.split('\0\0'):
        fields = dict(part.split(' ', 1) for part in block.split('\0') if ' ' in part)
        if 'worktree' not in fields:
            continue
        path = Path(fields['worktree'])
        if path.resolve() == root.resolve() or not path.exists() or 'bare' in block.split('\0'):
            continue
        try:
            common = git(path, 'merge-base', 'HEAD', 'origin/main')
            touched = changed_paths(path, common)
            result.append({'path': str(path), 'head': fields.get('HEAD'), 'changed_paths': touched,
                           'overlap': sorted(own_paths.intersection(touched))})
        except (OSError, subprocess.CalledProcessError):
            result.append({'path': str(path), 'error': 'Could not inspect this worktree'})
    return result


def start(root: Path, target: Path, acceptance: list[str]) -> dict:
    if target.exists():
        raise RuntimeError('Task baseline already exists; use finish or choose a new --record.')
    record = {'source': snapshot(root), 'origin_main': remote_tip(root), 'acceptance': acceptance}
    record['peers'] = peers(root, set(record['source']['changes']))
    write_json(target, record)
    return record


def finish(root: Path, target: Path) -> dict:
    baseline = json.loads(target.read_text(encoding='utf-8'))
    current = snapshot(root)
    origin = remote_tip(root)
    touched = set(changed_paths(root, baseline['source']['revision']))
    inherited = baseline['source']['changes']
    touched = {p for p in touched if p not in inherited or file_hash(root / p) != inherited[p]}
    report = {'baseline': str(target), 'source': current, 'origin_main': origin,
              'task_paths': sorted(touched), 'upstream_changes': [], 'overlap': []}
    old = baseline['origin_main']
    if old.get('verified') and origin.get('verified'):
        report['upstream_advanced'] = old['commit'] != origin['commit']
        if report['upstream_advanced']:
            changes = git(root, 'diff', '--name-only', old['commit'], origin['commit']).splitlines()
            report['upstream_changes'] = changes
            report['overlap'] = sorted(touched.intersection(changes))
    else:
        report['upstream_advanced'] = None
    report['peers'] = peers(root, touched)
    report['evidence'] = []
    for path in sorted((root / 'artifacts/verification').glob('**/summary.json')):
        try:
            evidence = json.loads(path.read_text(encoding='utf-8-sig'))
            source = evidence.get('source', {})
            report['evidence'].append({'path': str(path), 'matches_current_inputs':
                                      source.get('fingerprint') == current['fingerprint']
                                      if source.get('fingerprint') else None})
        except (OSError, ValueError):
            report['evidence'].append({'path': str(path), 'error': 'Unreadable summary'})
    write_json(target.with_name('handoff.json'), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'finish'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--accept', action='append', default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    target = args.record or root / 'artifacts/verification/task/context.json'
    if args.action == 'start' and not args.accept:
        parser.error('start requires at least one --accept criterion')
    try:
        report = start(root, target, args.accept) if args.action == 'start' else finish(root, target)
        print(json.dumps(report, indent=2))
        return 0 if report['origin_main']['verified'] else 2
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
