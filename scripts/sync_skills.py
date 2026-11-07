"""Diff and safely synchronize the two versioned BadShop development skills."""
from __future__ import annotations
import argparse
import difflib
import json
import os
from pathlib import Path
from dev_context import file_hash, write_json

NAMES = ('badshop-verification', 'badshop-provider-compat')
ROOT = Path(__file__).resolve().parents[1]


def inventory(folder: Path) -> dict:
    result = {}
    if folder.is_symlink():
        raise RuntimeError(f'Refusing symlinked skill directory: {folder}')
    if folder.exists():
        for path in folder.rglob('*'):
            if path.is_symlink():
                raise RuntimeError(f'Refusing symlinked skill resource: {path}')
            if path.is_file():
                result[path.relative_to(folder).as_posix()] = file_hash(path)
    return result


def synchronize(source: Path, destination: Path, *, apply: bool = False, adopt: bool = False) -> bool:
    manifest = destination / '.badshop-skills.json'
    previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    if adopt:
        if manifest.exists():
            raise RuntimeError('An installation baseline already exists; adoption will not replace it.')
        write_json(manifest, {name: inventory(destination / name) for name in NAMES})
        return True
    plans = []
    for name in NAMES:
        src, dst = source / name, destination / name
        wanted, actual = inventory(src), inventory(dst)
        if 'SKILL.md' not in wanted:
            raise RuntimeError(f'Missing canonical skill: {name}')
        if actual != wanted:
            print(f'{name}: changes available')
            for relative in sorted(set(wanted) | set(actual)):
                if wanted.get(relative) == actual.get(relative):
                    continue
                print(f'  {relative}')
                if relative.endswith(('.md', '.yaml')):
                    before = (dst / relative).read_text(encoding='utf-8').splitlines(True) if relative in actual else []
                    after = (src / relative).read_text(encoding='utf-8').splitlines(True) if relative in wanted else []
                    print(''.join(difflib.unified_diff(before, after, fromfile='installed/'+relative,
                                                     tofile='repository/'+relative)))
            if apply and actual and actual != previous.get(name):
                raise RuntimeError(f'{name}: installed edits differ from the recorded baseline; preserve and reconcile them first.')
        plans.append((name, src, dst, wanted, actual))
    if apply:
        # Preflight every skill before changing any of them.
        for name, src, dst, wanted, actual in plans:
            for relative in wanted:
                path = dst / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + '.badshop-new')
                with temporary.open('xb') as stream:
                    stream.write((src / relative).read_bytes())
                temporary.replace(path)
            for relative in set(actual) - set(wanted):
                (dst / relative).unlink()
        write_json(manifest, {name: wanted for name, _, _, wanted, _ in plans})
    return all(wanted == actual for _, _, _, wanted, actual in plans) or apply


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT / 'skills/development')
    p.add_argument('--destination', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'skills')
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--adopt', action='store_true', help='Record existing local hashes once; do not update content')
    args = p.parse_args()
    try:
        return 0 if synchronize(args.source, args.destination, apply=args.apply, adopt=args.adopt) else 1
    except (OSError, ValueError, RuntimeError) as exc:
        p.exit(2, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
