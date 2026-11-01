#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$repo_dir"
if ! command -v uv >/dev/null 2>&1; then
    printf 'Verification requires uv; see docs/development.md.\n' >&2
    exit 1
fi
exec uv run --project core --locked python scripts/verify.py "$@"
