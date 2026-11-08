"""Hash exactly the downloaded release assets; reject ambiguous GitHub asset names."""
import argparse
import hashlib
from pathlib import Path


def checksums(root: Path) -> str:
    assets = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    if not assets:
        raise ValueError("no release assets found")
    seen, lines = set(), []
    for path in assets:
        if path.name in seen or "\n" in path.name or "\r" in path.name:
            raise ValueError(f"ambiguous release asset name: {path.name!r}")
        seen.add(path.name)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {path.name}\n")
    return "".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    (args.root / "SHA256SUMS").write_text(checksums(args.root), encoding="utf-8")
