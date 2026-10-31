"""Run with uv run --project core --group build python packaging/build_core.py."""
import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', action='store_true', help='retained for compatibility; builds are always clean')
    parser.parse_args()
    # Release payloads must not reuse analysis from a previous core API revision.
    cmd = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', str(ROOT / 'packaging/core-dist'),
           '--workpath', str(ROOT / 'packaging/build'), str(ROOT / 'packaging/badshop-core.spec')]
    env = {**os.environ, 'LITELLM_LOCAL_MODEL_COST_MAP': 'True'}
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)
    inventory = sorted([{'name': d.metadata['Name'], 'version': d.version,
                         'license': d.metadata.get('License-Expression') or d.metadata.get('License', '')}
                        for d in importlib.metadata.distributions()], key=lambda d: d['name'].lower())
    (ROOT / 'packaging/core-dist/badshop-core/dependencies.json').write_text(json.dumps(inventory, indent=2))


if __name__ == '__main__':
    main()
