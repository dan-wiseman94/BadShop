import hashlib
import sys
from pathlib import Path

for directory in map(Path, sys.argv[1:]):
    expected = dict(line.split("  ", 1)[::-1] for line in (directory / "SHA256SUMS").read_text().splitlines())
    for asset in directory.iterdir():
        if asset.name == "SHA256SUMS":
            continue
        with asset.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        assert actual == expected[asset.name], f"Digest mismatch: {asset}"
        print(f"Verified {asset.name}: {actual}")
