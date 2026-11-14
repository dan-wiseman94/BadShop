"""Advisory size evidence from existing builds; never build or download an installer."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import time
import tempfile
from pathlib import Path

from dev_context import snapshot, write_json

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ('.deb', '.AppImage', '.exe', '.dmg', '.app.tar.gz', '.flatpak')


def history_workload(steps: int, turns: int) -> dict:
    """Measure real deterministic session edits/checkpoints and archive roundtrip.

    Explicit opt-in only: long histories intentionally expose archive limits.
    No provider, models, network, autosave or user project directories are used.
    """
    import io
    import psutil
    from PIL import Image
    from badshop.engine.errors import EngineError
    from badshop.session import branches, project
    from badshop.session.session import Session

    measurements = {}
    image = io.BytesIO()
    Image.new('RGB', (32, 32), (31, 67, 193)).save(image, format='PNG')
    with tempfile.TemporaryDirectory(prefix='badshop-history-measurement-') as folder:
        session = Session.new(output_dir=Path(folder))
        imported = session.import_image(image.getvalue(), 'deterministic-source')
        current = imported.id
        timings = []
        turn_timings = []
        for index in range(steps):
            # Spread exactly `turns` checkpoints over the history.
            for _ in range((index + 1) * turns // steps - index * turns // steps):
                start = time.perf_counter()
                branches.begin_turn(session)
                turn_timings.append(time.perf_counter() - start)
            start = time.perf_counter()
            step = session.run_tool('filter', {'image': current, 'names': ['invert']}, 'user')
            if step.status != 'done':
                raise RuntimeError(f'Workload failed at step {index}: {step.error}')
            current = step.outputs[-1]
            timings.append(time.perf_counter() - start)
        raw = {'edit_seconds': list(timings), 'checkpoint_seconds': list(turn_timings),
               'source_sha256': hashlib.sha256(image.getvalue()).hexdigest()}
        for name, samples in [('edit', timings), ('checkpoint', turn_timings)]:
            if samples:
                samples.sort()
                measurements[f'{name}_p50_seconds'] = samples[len(samples) // 2]
                measurements[f'{name}_p95_seconds'] = samples[min(len(samples) - 1, int(len(samples) * .95))]
        measurements['session_json_bytes'] = len(session.data.model_dump_json().encode())
        measurements['branches'] = len(session.data.branches)
        measurements['rss_bytes'] = psutil.Process().memory_info().rss
        destination = Path(folder) / 'history.badshop'
        try:
            start = time.perf_counter()
            project.save(session, destination)
            measurements['save_seconds'] = time.perf_counter() - start
            measurements['archive_bytes'] = destination.stat().st_size
            start = time.perf_counter()
            opened = project.open_project(destination)
            measurements['open_seconds'] = time.perf_counter() - start
            assert opened.artifacts.data(current) == session.artifacts.data(current)
            assert len(opened.data.steps) == steps
            assert len(opened.data.branches) == len(session.data.branches)
        except EngineError as error:
            return {'status': 'failed', 'error': error.message, 'measurements': measurements, 'raw': raw}
    return {'status': 'passed', 'measurements': measurements, 'raw': raw}


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
    parser.add_argument('kind', choices=('frontend', 'packages', 'history'))
    parser.add_argument('--steps', type=int, default=100)
    parser.add_argument('--turns', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.steps < 1 or args.turns < 0:
        parser.error('steps must be positive and turns must be nonnegative')
    data = {'schema': 1, 'status': 'passed', 'kind': args.kind, 'platform': platform.system(), 'machine': platform.machine(),
            'profile': 'production-build-v1', 'source': snapshot(ROOT),
            'lock_hashes': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                            for p in ('core/uv.lock', 'app/pnpm-lock.yaml', 'app/src-tauri/Cargo.lock')}}
    if args.kind == 'history':
        data.update(history_workload(args.steps, args.turns))
        data['profile'] = f'history-v1-steps-{args.steps}-turns-{args.turns}'
    else:
        data['measurements'] = sizes(ROOT, args.kind)
    write_json(args.output, data)
    if data['status'] != 'passed':
        raise SystemExit(f'Workload failed; evidence retained in {args.output}: {data["error"]}')
    baseline = json.loads(args.baseline.read_text(encoding='utf-8')) if args.baseline else None
    markdown = '# Resource measurements (advisory)\n\n' + comparison(data, baseline)
    markdown += '\n```json\n' + json.dumps(data, indent=2) + '\n```\n'
    write_json(args.output, data)
    args.output.with_suffix('.md').write_text(markdown, encoding='utf-8')
    print(markdown)


if __name__ == '__main__':
    main()
