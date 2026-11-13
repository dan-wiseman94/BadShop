"""Bind public release approval to tested source, exact bytes and retained acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, unquote, urlparse

from release_checksums import checksums
from update_manifest import TARGETS

ROOT = Path(__file__).resolve().parents[1]
MAIN_WORKFLOWS = ("core.yml", "desktop.yml", "maintenance.yml", "security.yml")
UPGRADE_CHECKS = ("signed_upgrade", "tampered_update", "download_retry", "process_cleanup",
                  "project_recovery", "rollback")
PLATFORM_CHECKS = {
    "windows-x64": ("install_uninstall", "native_files", "clipboard", "keychain", "os_trust", *UPGRADE_CHECKS),
    "macos-arm64": ("install_uninstall", "native_files", "clipboard", "keychain", "os_trust", *UPGRADE_CHECKS),
    "macos-x64": ("install_uninstall", "native_files", "clipboard", "keychain", "os_trust", *UPGRADE_CHECKS),
    "linux-appimage": ("runtime", "clipboard", *UPGRADE_CHECKS),
    "linux-deb": ("install_uninstall", "native_files", "keychain", "project_recovery", "package_update"),
    "linux-flatpak": ("install_uninstall", "native_files", "keychain", "project_recovery", "package_update"),
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def track(tag):
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        return "stable"
    if re.fullmatch(r"nightly-[0-9]{8}-[1-9][0-9]*-[1-9][0-9]*", tag):
        return "nightly"
    raise ValueError("Expected a stable vX.Y.Z or immutable nightly tag")


def assets(root):
    paths = [path for path in root.rglob("*") if path.is_file()]
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate release asset names")
    return dict(zip(names, paths, strict=True))


def inventory(files):
    result = {}
    for label in TARGETS:
        value = read(files[f"badshop-{label}.licenses.json"])
        if value["label"] != label or value["packages_without_notice_files"]:
            raise ValueError(f"Invalid or incomplete license inventory: {label}")
        reviews = value["manual_license_review"]
        if len({row["package"] for row in reviews}) != len(reviews):
            raise ValueError(f"Duplicate license reviews: {label}")
        result[label] = reviews
    return result


def stage(root, tag, source, run_id, attempt):
    """Build evidence can remain pending in a draft; only acceptance permits publication."""
    channel = track(tag)
    if not re.fullmatch(r"[0-9a-f]{40}", source) or run_id < 1 or attempt < 1:
        raise ValueError("Invalid candidate source or workflow identity")
    if channel == "nightly" and not tag.endswith(f"-{run_id}-{attempt}"):
        raise ValueError("Nightly tag must identify this build attempt")
    files = assets(root)
    inventory(files)
    value = {"schema": 1, "tag": tag, "track": channel, "source_sha": source,
             "run_id": run_id, "run_attempt": attempt, "version": read(files["latest.json"])["version"]}
    write(root / "release-candidate.json", value)
    return value


def verify_assets(root, repository, tag):
    files = assets(root)
    # Compare by filename because GitHub flattens the build artifact directories.
    def parse(text):
        result = {}
        for line in text.splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\\r\n]+)", line)
            if not match or match[2] in result:
                raise ValueError("Malformed or duplicate checksum entry")
            result[match[2]] = match[1]
        return result
    if parse(files["SHA256SUMS"].read_text()) != parse(checksums(root)):
        raise ValueError("Release bytes differ from SHA256SUMS")
    value = read(files["release-candidate.json"])
    channel = track(tag)
    if value["schema"] != 1 or value["tag"] != tag or value["track"] != channel:
        raise ValueError("Candidate identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", value["source_sha"]):
        raise ValueError("Invalid candidate SHA")
    if type(value["run_id"]) is not int or type(value["run_attempt"]) is not int:
        raise ValueError("Invalid workflow identity")
    if value["run_id"] < 1 or value["run_attempt"] < 1:
        raise ValueError("Invalid workflow identity")
    if channel == "nightly" and not tag.endswith(f"-{value['run_id']}-{value['run_attempt']}"):
        raise ValueError("Nightly tag/build mismatch")
    feed = read(files["latest.json"])
    expected_version = tag[1:] if channel == "stable" else value["version"]
    if channel == "nightly" and not re.fullmatch(
            rf"[0-9]+\.[0-9]+\.[0-9]+-nightly\.{value['run_id']}", expected_version):
        raise ValueError("Nightly version/build mismatch")
    if feed["version"] != expected_version or value["version"] != expected_version:
        raise ValueError("Update feed version mismatch")
    if set(feed["platforms"]) != {target for target, _ in TARGETS.values()}:
        raise ValueError("Incomplete update feed")
    for target, suffix in TARGETS.values():
        entry = feed["platforms"][target]
        url = urlparse(entry["url"])
        name = unquote(url.path.rsplit("/", 1)[-1])
        expected = f"https://github.com/{repository}/releases/download/{tag}/{quote(name, safe='')}"
        if entry["url"] != expected or not name.endswith(suffix) or name not in files:
            raise ValueError(f"Update feed points outside this candidate: {target}")
        signature = files[name + ".sig"].read_text().strip()
        if not signature or signature != entry["signature"]:
            raise ValueError(f"Update signature mismatch: {target}")
    for suffix, count in ((".deb", 1), (".flatpak", 1), (".dmg", 2)):
        if sum(name.endswith(suffix) for name in files) != count:
            raise ValueError(f"Incomplete installer set: {suffix}")
    for label in TARGETS:
        if f"badshop-{label}.sbom.json" not in files:
            raise ValueError(f"Missing SBOM: {label}")
    return value, inventory(files)


def acceptance_template(root, repository, tag):
    value, reviews = verify_assets(root, repository, tag)
    pending = {"result": "pending", "evidence": ""}
    return {"schema": 1, "tag": tag, "source_sha": value["source_sha"],
            "sha256sums": sha256(root / "SHA256SUMS"), "reviewed_by": "",
            "platforms": {label: {check: dict(pending) for check in checks}
                          for label, checks in PLATFORM_CHECKS.items()},
            "licenses": {label: {row["package"]: dict(pending) for row in rows}
                         for label, rows in reviews.items()}}


def verify_acceptance(root, repository, tag, acceptance):
    value, reviews = verify_assets(root, repository, tag)
    expected = {"schema": 1, "tag": tag, "source_sha": value["source_sha"],
                "sha256sums": sha256(root / "SHA256SUMS")}
    if any(acceptance.get(key) != content for key, content in expected.items()):
        raise ValueError("Acceptance does not identify these candidate bytes")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", acceptance.get("reviewed_by", "")):
        raise ValueError("Acceptance requires the reviewer's GitHub login")

    def evidence(row, allowed, label):
        url = urlparse(row.get("evidence", ""))
        if row.get("result") not in allowed or url.scheme != "https" or not url.netloc or not url.path.strip("/"):
            raise ValueError(f"Missing passing evidence: {label}")

    if set(acceptance["platforms"]) != set(PLATFORM_CHECKS):
        raise ValueError("Acceptance must cover every supported platform")
    for label, checks in PLATFORM_CHECKS.items():
        recorded = acceptance["platforms"][label]
        if set(recorded) != set(checks):
            raise ValueError(f"Acceptance checks differ from policy: {label}")
        for check in checks:
            # v1 explicitly permits unsigned OS binaries; updater signatures are mandatory.
            allowed = ("passed", "unsigned-disclosed") if check == "os_trust" else ("passed",)
            evidence(recorded[check], allowed, f"{label}/{check}")
    if set(acceptance["licenses"]) != set(reviews):
        raise ValueError("License acceptance must cover every inventory")
    for label, rows in reviews.items():
        recorded = acceptance["licenses"][label]
        if set(recorded) != {row["package"] for row in rows}:
            raise ValueError(f"Unresolved or stale license reviews: {label}")
        for package, row in recorded.items():
            evidence(row, ("approved",), f"{label}/{package}")
    return value


def gh_json(*args):
    return json.loads(subprocess.check_output(["gh", *args], text=True, encoding="utf-8"))


def require_unpublished(repository, tag):
    result = subprocess.run(["gh", "api", f"repos/{repository}/releases/tags/{quote(tag, safe='')}"],
                            capture_output=True, text=True, encoding="utf-8")
    value = json.loads(result.stdout)
    if result.returncode:
        if value.get("status") == "404":
            return
        raise RuntimeError(f"Cannot inspect existing release: {result.stderr}")
    if not value["draft"]:
        raise ValueError("Refusing to replace an already published release")


def verify_source(repository, source):
    subprocess.run(["git", "merge-base", "--is-ancestor", source, "origin/main"], cwd=ROOT, check=True)
    for workflow in MAIN_WORKFLOWS:
        data = gh_json("api", f"repos/{repository}/actions/workflows/{workflow}/runs",
                       "--method", "GET", "-f", "branch=main", "-f", "event=push",
                       "-f", f"head_sha={source}", "-f", "per_page=1")
        runs = data["workflow_runs"]
        if not runs or any(runs[0].get(key) != expected for key, expected in {
                "head_sha": source, "head_branch": "main", "event": "push",
                "path": f".github/workflows/{workflow}", "status": "completed", "conclusion": "success"}.items()):
            raise ValueError(f"Source lacks a successful main run: {workflow}")


def verify_github(root, repository, value):
    """Do not execute code from the candidate; current main owns promotion policy."""
    source, tag = value["source_sha"], value["tag"]
    verify_source(repository, source)
    run = gh_json("api", f"repos/{repository}/actions/runs/{value['run_id']}/attempts/{value['run_attempt']}")
    workflow = "release.yml" if value["track"] == "stable" else "nightly.yml"
    if any(run.get(key) != expected for key, expected in {
            "head_sha": source, "path": f".github/workflows/{workflow}",
            "status": "completed", "conclusion": "success", "run_attempt": value["run_attempt"]}.items()):
        raise ValueError("Candidate build run did not pass for this source and attempt")
    expected_branch = tag if value["track"] == "stable" else "main"
    events = ("push",) if value["track"] == "stable" else ("schedule", "workflow_dispatch")
    if run["head_branch"] != expected_branch or run["event"] not in events:
        raise ValueError("Candidate build came from an unexpected event")
    subprocess.run(["gh", "attestation", "verify", str(root / "SHA256SUMS"), "--repo", repository,
                    "--signer-workflow", f"{repository}/.github/workflows/{workflow}",
                    "--source-digest", source, "--deny-self-hosted-runners"], check=True)
    release = gh_json("api", f"repos/{repository}/releases/tags/{quote(tag, safe='')}")
    if release["prerelease"] != (value["track"] == "nightly"):
        raise ValueError("Release track differs from the accepted candidate")
    if release["target_commitish"] != source:
        raise ValueError("Draft target differs from verified source")
    files = assets(root)
    remote = release["assets"]
    if len(remote) != len(files) or {asset["name"] for asset in remote} != set(files):
        raise ValueError("Draft assets changed after download")
    for asset in remote:
        if asset["state"] != "uploaded" or asset["digest"] != "sha256:" + sha256(files[asset["name"]]):
            raise ValueError("Draft bytes changed after download")
    # Stable tags already exist. Nightly tags may first be created when the draft is published.
    refs = gh_json("api", f"repos/{repository}/git/matching-refs/tags/{quote(tag, safe='')}")
    exact = [ref for ref in refs if ref["ref"] == f"refs/tags/{tag}"]
    if exact:
        obj = exact[0]["object"]
        while obj["type"] == "tag":
            obj = gh_json("api", f"repos/{repository}/git/tags/{obj['sha']}")["object"]
        if obj["type"] != "commit" or obj["sha"] != source:
            raise ValueError("Release tag differs from verified source")
    elif value["track"] == "stable":
        raise ValueError("Stable tag is missing")
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "template", "check", "publish"))
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("tag")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "dan-wiseman94/BadShop"))
    parser.add_argument("--source", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--run-id", type=int, default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--attempt", type=int, default=os.environ.get("GITHUB_RUN_ATTEMPT"))
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    track(args.tag)
    if args.action == "stage":
        require_unpublished(args.repository, args.tag)
        stage(args.artifacts, args.tag, args.source, args.run_id, args.attempt)
    elif args.action == "template":
        if not args.output:
            parser.error("template requires --output")
        if args.output.exists():
            raise ValueError("Refusing to overwrite existing acceptance")
        write(args.output, acceptance_template(args.artifacts, args.repository, args.tag))
    else:
        acceptance_path = args.acceptance or ROOT / "packaging/release-acceptance" / f"{args.tag}.json"
        value = verify_acceptance(args.artifacts, args.repository, args.tag, read(acceptance_path))
        if args.action == "publish":
            if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
                raise ValueError("Publication must run through the main promotion workflow")
            release = verify_github(args.artifacts, args.repository, value)
            # A feed/upload failure may require a retry after the immutable release is public.
            # Revalidate everything, but never replace already-published bytes.
            if release["draft"]:
                gh_json("api", f"repos/{args.repository}/releases/{release['id']}", "--method", "PATCH",
                        "-F", "draft=false", "-F", f"prerelease={str(value['track'] == 'nightly').lower()}",
                        "-f", f"make_latest={'true' if value['track'] == 'stable' else 'false'}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"source={value['source_sha']}\ntrack={value['track']}\n")
        print(f"Accepted {args.tag} at {value['source_sha']}")


if __name__ == "__main__":
    main()
