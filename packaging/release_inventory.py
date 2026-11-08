"""Bundle dependency metadata and actual license notices from this build's installed sources.

Inventory scope is deliberately broader than runtime: Python includes the build environment,
Rust includes all resolved Cargo packages, and JavaScript is pnpm's production dependency set.
This is an inventory, not an automatic legal-compatibility opinion.
"""
import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
NOTICE = re.compile(r"^(?:licen[cs]e|copying|copyright|notice|authors)(?:$|[._-])", re.IGNORECASE)


def command(*args):
    binary = shutil.which(args[0])
    if not binary:
        raise RuntimeError(f"missing inventory prerequisite: {args[0]}")
    return json.loads(subprocess.check_output([binary, *args[1:]], cwd=ROOT, text=True))


def package_notices(root, extra=None):
    paths = [p for p in root.iterdir() if p.is_file() and NOTICE.match(p.name)]
    for folder in (root / "licenses", root / "LICENSES"):
        if folder.is_dir():
            paths.extend(p for p in folder.rglob("*") if p.is_file())
    if extra:
        path = (root / extra).resolve()
        path.relative_to(root.resolve())
        if path.is_file():
            paths.append(path)
    return paths


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    components, missing, reviews = [], [], []
    supplements = {row["purl"]: row for row in json.loads((ROOT / "packaging/license-notices.json").read_text())}

    def add(ecosystem, name, version, license_text, paths, scope):
        purl = f"pkg:{ecosystem}/{quote(name, safe='/')}@{quote(version, safe='')}"
        supplement = supplements.get(purl)
        if supplement:
            paths = [*paths, *(ROOT / "packaging" / row["file"] for row in supplement["notices"])]
            if supplement.get("review_required"):
                reviews.append({"package": purl, "reason": supplement["review_required"]})
        # Hashes avoid filenames derived from arbitrary upstream package labels.
        folder = destination / "notices" / hashlib.sha256(purl.encode()).hexdigest()[:20]
        notices = []
        for path in sorted(set(paths), key=str):
            raw = path.read_bytes()
            if len(raw) > 8 * 2**20:
                raise ValueError(f"unexpectedly large license notice: {name}")
            digest = hashlib.sha256(raw).hexdigest()
            target = folder / (digest + ".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            notices.append({"file": target.relative_to(destination).as_posix(), "sha256": digest,
                            "upstream_filename": path.name})
        component = {"type": "library", "name": name, "version": version, "purl": purl,
                     "bom-ref": purl, "properties": [{"name": "badshop:inventory-scope", "value": scope},
                        {"name": "badshop:license-notices", "value": json.dumps(notices)}]}
        if license_text:
            component["licenses"] = [{"license": {"name": license_text}}]
        if supplement:
            component["externalReferences"] = [{"type": "license", "url": row["source"]} for row in supplement["notices"]]
        if not notices:
            missing.append(purl)
        components.append(component)

    for distribution in importlib.metadata.distributions():
        paths = [Path(distribution.locate_file(p)) for p in distribution.files or []
                 if NOTICE.match(p.name) or any(part.lower() == "licenses" for part in p.parts)]
        paths = [p for p in paths if p.is_file()]
        add("pypi", distribution.metadata["Name"], distribution.version,
            distribution.metadata.get("License-Expression") or distribution.metadata.get("License", ""),
            paths, "installed Python build environment; includes runtime and build tools")
    for license_name, packages in command("pnpm", "--dir", "app", "licenses", "list", "--prod", "--json").items():
        for package in packages:
            for version, path in zip(package["versions"], package["paths"], strict=True):
                add("npm", package["name"], version, license_name, package_notices(Path(path)),
                    "production JavaScript dependency graph")
    metadata = command("cargo", "metadata", "--locked", "--format-version", "1",
                       "--manifest-path", "app/src-tauri/Cargo.toml")
    for package in metadata["packages"]:
        if package["source"] is None:
            continue
        add("cargo", package["name"], package["version"], package["license"],
            package_notices(Path(package["manifest_path"]).parent, package.get("license_file")),
            "resolved Cargo graph; includes build and non-host target dependencies")
        if "MPL-2.0" in (package["license"] or ""):
            source = Path(package["manifest_path"]).parent
            target = destination / "covered-source" / f"{package['name']}-{package['version']}"
            shutil.copytree(source, target, dirs_exist_ok=True)
            components[-1]["properties"].append({"name": "badshop:covered-source", "value": target.relative_to(destination).as_posix()})
    # Deduplicate packages appearing through multiple dependency paths, preserving their notices.
    by_id = {}
    for component in components:
        by_id.setdefault(component["purl"], component)
    value = {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
             "components": sorted(by_id.values(), key=lambda p: p["purl"])}
    (destination / "sbom.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    (destination / "coverage.json").write_text(json.dumps({"components": len(by_id),
        "packages_without_notice_files": sorted(set(missing)),
        "manual_license_review": reviews,
        "review": "Missing files need license review before public release; metadata alone is not a license notice."}, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / "packaging/THIRD_PARTY_NOTICES.md", destination / "README.md")
    print(f"Inventoried {len(by_id)} dependencies; {len(set(missing))} missing notice files; {len(reviews)} require manual license review.")
    if missing:
        raise ValueError("license notice files are missing; see coverage.json before bundling")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "packaging/core-dist/badshop-core/legal")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+", args.label):
        parser.error("label must contain lowercase letters, digits and hyphens")
    result = build(args.destination)
    (ROOT / "packaging" / f"badshop-{args.label}.sbom.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
