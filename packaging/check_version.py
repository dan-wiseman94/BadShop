"""Refuse publication when the tag and packaged application versions disagree."""
import ast
import json
from pathlib import Path
import sys
import tomllib


def check_versions(root: Path, tag: str | None = None) -> str:
    def toml(name):
        return tomllib.loads((root / name).read_text(encoding="utf-8"))

    versions = {
        "core/pyproject.toml": toml("core/pyproject.toml")["project"]["version"],
        "app/package.json": json.loads((root / "app/package.json").read_text())["version"],
        "app/src-tauri/tauri.conf.json": json.loads((root / "app/src-tauri/tauri.conf.json").read_text())["version"],
        "app/src-tauri/Cargo.toml": toml("app/src-tauri/Cargo.toml")["package"]["version"],
    }
    tree = ast.parse((root / "core/src/badshop/__init__.py").read_text())
    versions["core/src/badshop/__init__.py"] = next(
        ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )
    for filename, name in (("core/uv.lock", "badshop"), ("app/src-tauri/Cargo.lock", "badshop-desktop")):
        matches = [package["version"] for package in toml(filename)["package"] if package["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Expected one application package in {filename}")
        versions[filename] = matches[0]
    expected = versions["core/pyproject.toml"]
    if tag is not None:
        versions["release tag"] = tag.removeprefix("refs/tags/").removeprefix("v")
    mismatches = {name: version for name, version in versions.items() if version != expected}
    if mismatches:
        raise ValueError(f"Expected application version {expected}; mismatches: {mismatches}")
    return expected


if __name__ == "__main__":
    version = check_versions(Path(__file__).resolve().parents[1], sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Application versions agree: {version}")
