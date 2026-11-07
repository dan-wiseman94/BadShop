"""Conservatively classify changed paths; unknown paths receive full coverage."""
from __future__ import annotations
import argparse
import json
import os
import subprocess


def classify(paths: list[str], full: bool = False) -> dict:
    if full:
        return dict(core=True, frontend=True, native=True, reason='Explicit full validation')
    result = dict(core=False, frontend=False, native=False)
    for path in paths:
        if (path.endswith('.md') and path.startswith(('docs/', 'skills/'))) or path in ('AGENTS.md', 'README.md', 'LICENSE'):
            continue
        if path.startswith(('core/tests/', 'scripts/tests/')):
            result['core'] = True
        elif path.startswith(('app/tests/', 'app/e2e/')) or path == 'app/playwright.config.ts':
            result['frontend'] = True
        elif path.startswith('app/src/'):
            result['frontend'] = True
        else:
            result.update(core=True, frontend=True, native=True)
    return result | {'reason': 'Changed-path classification; unknown/shared paths broaden coverage'}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base')
    p.add_argument('--head', default='HEAD')
    p.add_argument('--full', action='store_true')
    args = p.parse_args()
    paths = []
    full = args.full
    if not args.base or set(args.base) == {'0'}:
        full = True
    else:
        diff = subprocess.run(['git', 'diff', '--name-only', '-z', args.base, args.head], capture_output=True)
        if diff.returncode:
            full = True
        else:
            paths = [x.decode() for x in diff.stdout.split(b'\0') if x]
    scope = classify(paths, full)
    print(json.dumps(scope, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
            for key in ('core', 'frontend', 'native'):
                out.write(f'{key}={str(scope[key]).lower()}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
