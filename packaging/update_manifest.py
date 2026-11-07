"""Build the Tauri update feed from the four verified release artifacts."""
import argparse
import json
from pathlib import Path
from urllib.parse import quote


TARGETS = {
    "linux-x64": ("linux-x86_64", ".AppImage"),
    "windows-x64": ("windows-x86_64", ".exe"),
    "macos-arm64": ("darwin-aarch64", ".app.tar.gz"),
    "macos-x64": ("darwin-x86_64", ".app.tar.gz"),
}


def manifest(root: Path, tag: str, repository: str) -> dict:
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
    return {"version": tag.removeprefix("v"), "platforms": platforms}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("tag")
    parser.add_argument("repository")
    args = parser.parse_args()
    (args.artifacts / "latest.json").write_text(
        json.dumps(manifest(args.artifacts, args.tag, args.repository), indent=2) + "\n"
    )
