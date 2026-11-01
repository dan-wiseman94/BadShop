#!/usr/bin/env bash
# Start the desktop app from a source checkout.
set -euo pipefail

if [[ $# -gt 0 ]]; then
    if [[ $# -eq 1 && ( $1 == --help || $1 == -h ) ]]; then
        cat <<'EOF'
Usage: ./start.sh

Sync locked dependencies and launch the badshop desktop app in development mode.
Requires uv, Node/npm, pnpm 10 (or Corepack), Rust/Cargo, and Tauri's native libraries.
The first launch downloads dependencies and compiles the desktop shell.
Close the app or press Ctrl+C in this terminal to stop it.
Set BADSHOP_DEV_PORT to use a different development port (default: 1420).
See README.md and docs/releasing.md for setup instructions.
EOF
        exit 0
    fi
    printf 'Usage: %s [--help]\n' "$0" >&2
    exit 2
fi

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$repo_dir"

# The debug shell starts the source core with uv; it needs no frozen release resources.
tauri_args=(dev --config "$repo_dir/app/src-tauri/tauri.source.conf.json")
if [[ -n ${BADSHOP_DEV_PORT:-} ]]; then
    if [[ ! $BADSHOP_DEV_PORT =~ ^[0-9]{1,5}$ ]] ||
        (( 10#$BADSHOP_DEV_PORT < 1 || 10#$BADSHOP_DEV_PORT > 65535 )); then
        printf 'BADSHOP_DEV_PORT must be a port number from 1 to 65535.\n' >&2
        exit 2
    fi
    dev_port=$((10#$BADSHOP_DEV_PORT))
    printf -v dev_config '{"build":{"beforeDevCommand":"npm run dev -- --port %d --strictPort","devUrl":"http://127.0.0.1:%d"}}' "$dev_port" "$dev_port"
    tauri_args+=(--config "$dev_config")
fi

missing=()
for program in uv node npm cargo; do
    if ! command -v "$program" >/dev/null 2>&1; then
        missing+=("$program")
    fi
done

if command -v pnpm >/dev/null 2>&1; then
    pnpm_command=(pnpm)
elif command -v corepack >/dev/null 2>&1; then
    pnpm_command=(corepack pnpm@10)
else
    missing+=("pnpm 10 (or Corepack)")
fi

if (( ${#missing[@]} )); then
    printf 'Missing prerequisite: %s\n' "${missing[@]}" >&2
    printf 'Install the prerequisites listed in README.md and docs/releasing.md, then retry.\n' >&2
    exit 1
fi

printf 'Preparing Python dependencies…\n'
uv sync --project core --locked
printf 'Preparing desktop dependencies…\n'
"${pnpm_command[@]}" --dir app install --frozen-lockfile
printf 'Starting badshop (the first Rust build can take several minutes)…\n'
exec "${pnpm_command[@]}" --dir app tauri "${tauri_args[@]}"
