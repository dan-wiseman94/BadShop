"""Advisory production growth against a Git base; never execute code from that base."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

import lizard

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ('core/src/', 'app/src/', 'app/src-tauri/src/')
SOURCE_SUFFIXES = {'.py', '.ts', '.tsx', '.rs', '.css'}
MANIFESTS = ('core/pyproject.toml', 'app/package.json', 'app/src-tauri/Cargo.toml')


def safeguard_changes(root: Path, base: str, head: str | None) -> list[tuple[str, str]]:
    """Review signals only: a changed assertion is not proof of weakened coverage."""
    revisions = [base, head] if head else [base]
    paths = git(root, 'diff', '--name-only', '-z', *revisions).rstrip('\0').split('\0')
    if not head:
        paths += git(root, 'ls-files', '--others', '--exclude-standard', '-z').rstrip('\0').split('\0')
    signals = []
    for path in sorted(set(paths) - {''}):
        reason = None
        if path.startswith('reference/'):
            reason = 'Reference behavior or tool catalog changed'
        elif path.startswith('core/tests/fixtures/'):
            reason = 'Golden, provider transcript, or compatibility fixture changed'
        elif path.startswith('.github/workflows/') or path in ('scripts/ci_scope.py', 'scripts/verify.py'):
            reason = 'CI selection, execution, or enforcement changed'
        elif path in ('.importlinter', 'app/knip.json', 'core/pyproject.toml', 'app/package.json',
                      'app/playwright.config.ts', 'app/vitest.config.ts'):
            reason = 'Analyzer, dependency, or test configuration changed'
        elif path.startswith(('scripts/maintenance', 'scripts/prove_regression', 'scripts/generate_wire_types')):
            reason = 'Maintenance guard or its negative control changed'
        elif path in ('AGENTS.md', 'docs/diff-review.md', 'docs/development.md', '.github/pull_request_template.md'):
            reason = 'Development or safeguard-review policy changed'
        elif path.endswith('conftest.py'):
            reason = 'Shared test setup or collection changed'
        elif path.startswith(('core/tests/', 'app/tests/', 'app/e2e/', 'scripts/tests/')):
            diff = git(root, 'diff', '--no-ext-diff', '--unified=0', *revisions, '--', path)
            if not head and not diff and (root / path).is_file():
                diff = '\n'.join('+' + line for line in (root / path).read_text(encoding='utf-8').splitlines())
            if re.search(r'^-[^-].*\b(assert|expect|raises|assert\w+)\b', diff, re.M):
                reason = 'Assertions removed or rewritten; identify remaining failure coverage'
            if re.search(r'^\+[^+].*(\b(skip|skipif|xfail|only)\b|noqa|istanbul ignore|v8 ignore)', diff, re.M):
                reason = 'Test selection, skip, or suppression added'
        if reason:
            signals.append((path, reason))
    return signals


def safeguards_report(signals: list[tuple[str, str]]) -> str:
    text = '\n## Safeguard changes requiring review\n\n'
    text += ('These are change signals, not findings. Explain intentional baseline/coverage changes in\n'
             'the PR’s **Safeguard changes** section, including why the remaining check catches the failure.\n\n')
    return text + ('\n'.join(f'- `{path}`: {reason}' for path, reason in signals) or 'None.') + '\n'


def review_note(body: str) -> str:
    match = re.search(r'^## Safeguard changes\s*\n(.*?)(?=^## |\Z)', body, re.M | re.S)
    if not match:
        return ''
    note = re.sub(r'<!--.*?-->', '', match[1], flags=re.S).strip()
    return '' if note.lower() in ('none', 'n/a', 'todo', 'none.', 'n/a.') else note


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, encoding='utf-8')


def snapshot(root: Path, revision: str | None) -> dict[str, str]:
    names = (git(root, 'ls-tree', '-r', '--name-only', '-z', revision) if revision else
             git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'))
    result = {}
    for name in sorted(set(names.rstrip('\0').split('\0'))):
        if name not in MANIFESTS and not (name.startswith(SOURCE_ROOTS) and Path(name).suffix in SOURCE_SUFFIXES):
            continue
        if revision:
            result[name] = git(root, 'show', f'{revision}:{name}')
        elif (root / name).is_file():
            result[name] = (root / name).read_text(encoding='utf-8')
    return result


def dependencies(files: dict[str, str]) -> dict[str, str]:
    result = {}
    for path in MANIFESTS:
        if path not in files:
            continue
        data = json.loads(files[path]) if path.endswith('.json') else tomllib.loads(files[path])
        if path == 'core/pyproject.toml':
            groups = {'runtime': data['project'].get('dependencies', []), **data.get('dependency-groups', {})}
            for group, values in groups.items():
                for value in values:
                    if isinstance(value, str):
                        # Preserve platform-specific requirements separately.
                        name = re.split(r'[<>=!~\[; ]', value, maxsplit=1)[0]
                        marker = value.partition(';')[2].strip()
                        result[f'{path}:{group}:{name}:{marker}'] = value
        else:
            def visit(table, prefix=''):
                for key, value in table.items():
                    if key in ('dependencies', 'devDependencies', 'dev-dependencies', 'build-dependencies'):
                        for name, spec in value.items():
                            result[f'{path}:{prefix}{key}:{name}'] = json.dumps(spec, sort_keys=True)
                    elif isinstance(value, dict):
                        visit(value, prefix + key + '.')
            visit(data)
    return result


def complexity(path: str, source: str) -> dict[str, int]:
    if Path(path).suffix == '.css':
        return {}
    functions = lizard.analyze_file.analyze_source_code(path, source).function_list
    result = {}
    for function in functions:
        # Same-name overloads/callbacks are represented by their maximum, not a guessed identity.
        key = function.long_name
        result[key] = max(result.get(key, 0), function.cyclomatic_complexity)
    return result


def report(before: dict[str, str], after: dict[str, str]) -> str:
    lines = ['# Maintenance growth (advisory)', '',
             'Physical source lines include comments/blank lines. CCN is Lizard cyclomatic complexity;',
             'same-name functions use their maximum. These are review signals, not limits.', '',
             '| Production file | Before lines | After lines | Delta |', '| --- | ---: | ---: | ---: |']
    increases = []
    for path in sorted(before.keys() | after.keys()):
        if path in MANIFESTS or before.get(path) == after.get(path):
            continue
        old, new = before.get(path, ''), after.get(path, '')
        a, b = len(old.splitlines()), len(new.splitlines())
        lines.append(f'| `{path}` | {a} | {b} | {b-a:+d} |')
        old_cc = complexity(path, old)
        for name, value in complexity(path, new).items():
            previous = old_cc.get(name, 0)
            if value > previous:
                label = name.replace('|', '\\|').replace('`', '')
                increases.append((value-previous, f'- `{path}` — `{label}`: {previous} → {value}'))
    old_total = sum(len(s.splitlines()) for p, s in before.items() if p not in MANIFESTS)
    new_total = sum(len(s.splitlines()) for p, s in after.items() if p not in MANIFESTS)
    lines += ['', f'Total production lines: {old_total} → {new_total} ({new_total-old_total:+d}).', '',
              '## Function complexity increases', '']
    lines += [text for _, text in sorted(increases, reverse=True)] or ['None.']
    lines += ['', '## Direct dependency changes (runtime and development)', '']
    old_deps, new_deps = dependencies(before), dependencies(after)
    changes = []
    for key in sorted(old_deps.keys() | new_deps.keys()):
        if old_deps.get(key) != new_deps.get(key):
            changes.append(f'- `{key}`: `{old_deps.get(key, "absent")}` → `{new_deps.get(key, "removed")}`')
    lines += changes or ['None.']
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='PR base SHA or local base ref; compare from its merge-base')
    parser.add_argument('--head', help='Commit to inspect; omit to inspect current tracked/untracked source')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--review-event', type=Path, help='PR event JSON; require a safeguard explanation when flagged')
    args = parser.parse_args()
    base = git(ROOT, 'rev-parse', '--verify', args.base + '^{commit}').strip()
    head = git(ROOT, 'rev-parse', '--verify', (args.head or 'HEAD') + '^{commit}').strip()
    base = git(ROOT, 'merge-base', base, head).strip()
    text = f'Base: `{base}`; head: `{head if args.head else "working tree"}`\n\n'
    text += report(snapshot(ROOT, base), snapshot(ROOT, head if args.head else None))
    signals = safeguard_changes(ROOT, base, head if args.head else None)
    text += safeguards_report(signals)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')
    if args.review_event and signals:
        event = json.loads(args.review_event.read_text(encoding='utf-8'))
        if 'pull_request' in event and not review_note(event['pull_request'].get('body') or ''):
            raise SystemExit('Explain flagged changes under "## Safeguard changes" in the PR body. '
                             'This checks presence; the reviewer must assess the explanation.')


if __name__ == '__main__':
    main()
