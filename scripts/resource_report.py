"""Advisory size evidence from existing builds; never build or download an installer."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
from pathlib import Path

from dev_context import snapshot, write_json

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ('.deb', '.AppImage', '.exe', '.dmg', '.app.tar.gz', '.flatpak')


def sizes(root: Path, kind: str) -> dict[str, int]:
    if kind == 'frontend':
        folder = root / 'app/dist'
        if not (folder / 'index.html').is_file():
            raise ValueError('Frontend build is missing; run pnpm --dir app build first')
        files = sorted(p for p in folder.rglob('*') if p.is_file() and not p.is_symlink())
        return {'total_bytes': sum(p.stat().st_size for p in files),
                'javascript_bytes': sum(p.stat().st_size for p in files if p.suffix == '.js'),
                'javascript_gzip_bytes': sum(len(gzip.compress(p.read_bytes(), mtime=0))
                                             for p in files if p.suffix == '.js'),
                'css_bytes': sum(p.stat().st_size for p in files if p.suffix == '.css')}
    bundle = root / 'app/src-tauri/target/release/bundle'
    files = [p for p in bundle.rglob('*') if p.is_file() and p.name.endswith(INSTALLERS)]
    files += list((root / 'packaging').glob('*.flatpak'))
    if not files:
        raise ValueError('No packaged installers found; this is not a passing measurement')
    # Versioned filenames change every release. Compare like package formats,
    # while refusing ambiguous outputs instead of choosing an arbitrary file.
    result = {}
    for path in sorted(files):
        suffix = next(ext for ext in INSTALLERS if path.name.endswith(ext))
        key = f'installer_{suffix.lstrip(".")}_bytes'
        if key in result:
            raise ValueError(f'Ambiguous package outputs for {suffix}')
        result[key] = path.stat().st_size
    core = root / 'packaging/core-dist/badshop-core'
    if not core.is_dir():
        raise ValueError('Packaged core directory is missing')
    result['unpacked_core_bytes'] = sum(p.stat().st_size for p in core.rglob('*')
                                        if p.is_file() and not p.is_symlink())
    return result


def comparison(current: dict, baseline: dict | None) -> str:
    if current.get('status', 'passed') != 'passed' or (baseline and baseline.get('status', 'passed') != 'passed'):
        raise ValueError('Failed measurements cannot be used as a resource baseline')
    if baseline is None:
        return 'No comparison baseline supplied; retain this report as a candidate baseline.\n'
    identity = ('schema', 'kind', 'platform', 'machine', 'profile')
    if any(current.get(key) != baseline.get(key) for key in identity):
        raise ValueError('Incompatible resource baseline (schema, kind, platform, machine, or profile)')
    lines = ['| Measurement | Baseline | Current | Delta |', '| --- | ---: | ---: | ---: |']
    for key, value in current['measurements'].items():
        old = baseline['measurements'].get(key)
        delta = f'{value - old:+.2f}' if isinstance(old, (int, float)) else 'new'
        lines.append(f'| `{key}` | {old if old is not None else "absent"} | {value} | {delta} |')
    for key in baseline['measurements'].keys() - current['measurements'].keys():
        lines.append(f'| `{key}` | {baseline["measurements"][key]} | absent | removed |')
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('frontend', 'packages'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    data = {'schema': 1, 'status': 'passed', 'kind': args.kind, 'platform': platform.system(), 'machine': platform.machine(),
            'profile': 'production-build-v1', 'source': snapshot(ROOT), 'measurements': sizes(ROOT, args.kind),
            'lock_hashes': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                            for p in ('core/uv.lock', 'app/pnpm-lock.yaml', 'app/src-tauri/Cargo.lock')}}
    baseline = json.loads(args.baseline.read_text(encoding='utf-8')) if args.baseline else None
    markdown = '# Resource measurements (advisory)\n\n' + comparison(data, baseline)
    markdown += '\n```json\n' + json.dumps(data, indent=2) + '\n```\n'
    write_json(args.output, data)
    args.output.with_suffix('.md').write_text(markdown, encoding='utf-8')
    print(markdown)


if __name__ == '__main__':
    main()
