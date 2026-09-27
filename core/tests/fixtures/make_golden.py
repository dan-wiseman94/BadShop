"""Regenerate tests/fixtures/golden.json, the pinned outputs test_golden.py checks.

Run it only on purpose: when a uv.lock change moves Pillow, NumPy, OpenCV or onnxruntime, or when a
change to the engine's pixels is intended. Then review the diff (which cases moved, and why) before
committing it:

    cd core && uv run python tests/fixtures/make_golden.py

It needs the models and fonts the `models` tests use (downloaded once into core/.test-cache)."""

import json
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))

import conftest  # noqa: E402,F401  (points the data dirs at core/.test-cache, as the tests do)
from test_golden import CASES, GOLDEN, run_case, versions  # noqa: E402


def main() -> None:
    cases = {}
    for case_id in CASES:
        with tempfile.TemporaryDirectory() as folder:
            cases[case_id] = run_case(case_id, Path(folder).resolve())
        print(f"{case_id}: {len(cases[case_id]['files'])} file(s)")
    GOLDEN.write_text(json.dumps({"versions": versions(), "cases": cases}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    main()
