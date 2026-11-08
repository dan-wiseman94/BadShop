"""Gate cargo-audit warnings with explicit, version-bound, expiring reviews.

Known vulnerabilities always fail. Network/tool errors must fail in the calling
command before this script; missing or malformed JSON also fails, never passes.
"""
import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(report, reviews, today=None):
    today = today or datetime.now(UTC).date()
    vulnerabilities = report["vulnerabilities"]
    if vulnerabilities["found"] or vulnerabilities["list"]:
        raise ValueError("Rust dependencies have known vulnerabilities; resolve them before release")
    reviewed = {(r["package"], r["version"], r["advisory"], r["kind"]): r for r in reviews}
    failures = []
    for kind, warnings in report["warnings"].items():
        for warning in warnings:
            identity = (warning["package"]["name"], warning["package"]["version"], warning["advisory"]["id"], kind)
            review = reviewed.get(identity)
            if not review or not review["reason"].strip() or date.fromisoformat(review["expires"]) <= today:
                failures.append(" / ".join(identity))
    if failures:
        raise ValueError("Rust advisories need a current review: " + "; ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    reviews = json.loads((ROOT / "packaging/rust-advisory-review.json").read_text())
    check(json.loads(args.report.read_text()), reviews)
    print("No known Rust vulnerabilities; remaining advisory notices have version-bound, expiring reviews.")


if __name__ == "__main__":
    main()
