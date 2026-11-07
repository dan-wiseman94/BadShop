"""Run focused regression tests with and without one production guard in a temporary copy."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "core" / "src"
SERVER = "badshop/server/app.py"
STATE = "core/tests/test_state_machines.py"
PROBES = {
    "paste-size": (
        SERVER, "elif _pasted_size(data) > MAX_PASTE_BYTES:", "elif False:",
        "core/tests/test_server_app.py::test_a_pasted_image_has_the_import_limit_and_is_decoded_off_the_loop",
    ),
    "document-ownership": (
        SERVER, 'if self.session is not session or session.data.steps is not timeline:\n'
        '                raise EngineError("the session changed while the image was being read",',
        'if False:\n                raise EngineError("the session changed while the image was being read",',
        f"{STATE}::test_slow_import_cannot_cross_a_document_replacement[new]",
    ),
    "approval-dependency": (
        "badshop/session/session.py", "        self._refuse_later(step, pos, params)\n        return params",
        "        return params", f"{STATE}::test_session_run_also_guards_approval_edits",
    ),
}


def run_test(source: Path, test: str, log: Path) -> tuple[int, str]:
    # Put the selected source first, then assert which package the child imported.
    bootstrap = ("import pathlib, sys, badshop; "
                 "assert pathlib.Path(badshop.__file__).resolve().is_relative_to(pathlib.Path(sys.argv.pop(1))); "
                 "import pytest; raise SystemExit(pytest.main(sys.argv[1:]))")
    command = [sys.executable, "-c", bootstrap, str(source), test, "-q", "--tb=short"]
    with TemporaryDirectory(prefix="badshop-regression-data-") as data:
        env = os.environ | {"PYTHONPATH": str(source), "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                            "PYTHONIOENCODING": "utf-8", "PYTEST_ADDOPTS": ""}
        for key in ("BADSHOP_CONFIG_DIR", "BADSHOP_DATA_DIR", "BADSHOP_LOG_DIR", "BADSHOP_OUT",
                    "REMBG_HOME", "U2NET_HOME"):
            env[key] = str(Path(data) / key.lower())
        env.pop("BADSHOP_FAKE_PROVIDER", None)
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=60, check=False)
            output = result.stdout.decode("utf-8", errors="replace")
            code = result.returncode
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or b"").decode("utf-8", errors="replace") + "\nTimed out after 60 seconds.\n"
            code = -1
    log.write_text(json.dumps(command) + "\n" + output, encoding="utf-8")
    return code, output


def prove(name: str, output: Path) -> dict:
    relative, before, after, test = PROBES[name]
    text = (SOURCE / relative).read_text(encoding="utf-8")
    if text.count(before) != 1:
        return {"probe": name, "passed": False, "error": "Expected guard changed. Review the probe."}
    baseline, _ = run_test(SOURCE, test, output / f"{name}-baseline.log")
    if baseline != 0:
        return {"probe": name, "passed": False, "baseline_exit": baseline}
    with TemporaryDirectory(prefix="badshop-regression-source-") as directory:
        source = Path(directory) / "src"
        shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (source / relative).write_text(text.replace(before, after), encoding="utf-8")
        mutant, report = run_test(source, test, output / f"{name}-guard-removed.log")
    return {"probe": name, "test": test, "baseline_exit": baseline, "mutant_exit": mutant,
            "passed": mutant == 1 and "DID NOT RAISE" in report and "1 failed" in report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", choices=[*PROBES, "all"])
    parser.add_argument("--out", type=Path, required=True, help="new evidence directory")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    results = [prove(name, args.out) for name in (PROBES if args.probe == "all" else [args.probe])]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    changes = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    evidence = json.dumps({"revision": revision, "working_tree": changes, "results": results}, indent=2) + "\n"
    (args.out / "summary.json").write_text(evidence, encoding="utf-8")
    print(evidence, end="")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
