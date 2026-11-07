"""Pin Windows encoded-byte variants only after shared pixels/metadata agree.

Run deliberately with the locked Windows interpreter. No models are downloaded.
The shared golden.json (including every decoded pixel hash) remains unchanged.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_golden import CASES, WINDOWS_ENCODINGS, _golden, codec_versions, run_case, versions  # noqa: E402


def main():
    if sys.platform != "win32":
        raise SystemExit("Run this encoder-pin review on Windows")
    golden, cases = _golden(), {}
    for case, (_, _, models) in CASES.items():
        if models:
            continue
        with tempfile.TemporaryDirectory() as folder:
            actual = run_case(case, Path(folder))
        expected = golden["cases"][case]
        assert actual["lines"] == expected["lines"], case
        assert actual["data"] == expected["data"], case
        assert actual["files"].keys() == expected["files"].keys(), case
        for name, record in actual["files"].items():
            base = expected["files"][name]
            assert {**record, "sha256": base["sha256"]} == base, (case, name, "pixels changed")
            if record["sha256"] != base["sha256"]:
                cases.setdefault(case, {})[name] = record["sha256"]
        print(f"{case}: shared pixels and metadata match")
    WINDOWS_ENCODINGS.write_text(json.dumps({"versions": versions(), "codecs": codec_versions(),
                                             "cases": cases}, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
