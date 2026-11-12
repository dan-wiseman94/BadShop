"""Build the Tauri update feed from the four verified release artifacts."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote


TARGETS = {
    "linux-x64": ("linux-x86_64", ".AppImage"),
    "windows-x64": ("windows-x86_64", ".exe"),
    "macos-arm64": ("darwin-aarch64", ".app.tar.gz"),
    "macos-x64": ("darwin-x86_64", ".app.tar.gz"),
}


def nightly_version(base: str, run_id: str) -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", base) or not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("Nightly requires a stable base version and a positive run ID")
    return f"{base}-nightly.{run_id}"


def can_promote_nightly(previous: dict, candidate: dict, *, feed_missing: bool = False) -> bool:
    # A rerun of an older source must not roll the channel pointer backwards.
    def run_id(feed):
        match = re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-nightly\.([1-9][0-9]*)", feed["version"])
        if not match:
            raise ValueError("Invalid nightly feed version")
        return int(match[1])
    old, new = run_id(previous), run_id(candidate)
    return new > old or (new == old and feed_missing)


def manifest(root: Path, tag: str, repository: str, version: str | None = None) -> dict:
    platforms = {}
    for label, (target, suffix) in TARGETS.items():
        matches = list((root / f"badshop-{label}").rglob(f"*{suffix}"))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {suffix} update for {label}, got {len(matches)}")
        artifact = matches[0]
        signature = Path(str(artifact) + ".sig").read_text().strip()
        if not signature:
            raise ValueError(f"Empty signature: {artifact}")
        platforms[target] = {
            "signature": signature,
            "url": f"https://github.com/{repository}/releases/download/{quote(tag, safe='')}/{quote(artifact.name, safe='')}",
        }
    return {"version": version or tag.removeprefix("v"), "platforms": platforms}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("tag")
    parser.add_argument("repository")
    parser.add_argument("--nightly-run")
    args = parser.parse_args()
    version = None
    if args.nightly_run:
        from check_version import check_versions
        version = nightly_version(check_versions(Path(__file__).resolve().parents[1]), args.nightly_run)
    (args.artifacts / "latest.json").write_text(
        json.dumps(manifest(args.artifacts, args.tag, args.repository, version), indent=2) + "\n"
    )
