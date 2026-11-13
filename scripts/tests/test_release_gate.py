"""Candidate acceptance rejects stale evidence and exercises publication without external writes."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
import release_gate as gate
from release_checksums import checksums
from update_manifest import manifest

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
REPO = "owner/repo"
TAG = "v1.2.3"


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "assets"
        self.root.mkdir()
        for label, (_, suffix) in gate.TARGETS.items():
            folder = self.root / f"badshop-{label}"
            folder.mkdir()
            (folder / f"badshop-{label}{suffix}").write_bytes(b"candidate installer")
            (folder / f"badshop-{label}{suffix}.sig").write_text("fixture-signature")
            gate.write(folder / f"badshop-{label}.sbom.json", {"components": []})
            gate.write(folder / f"badshop-{label}.licenses.json", {
                "label": label, "packages_without_notice_files": [],
                "manual_license_review": [{"package": "pkg:cargo/example@1", "reason": "review required"}]})
        for name in ("badshop.deb", "badshop.flatpak", "badshop-arm.dmg", "badshop-x64.dmg"):
            (self.root / name).write_bytes(b"installer")
        gate.write(self.root / "latest.json", manifest(self.root, TAG, REPO))
        gate.stage(self.root, TAG, SHA, 123, 1)
        self.rehash()
        self.acceptance = gate.acceptance_template(self.root, REPO, TAG)
        self.acceptance["reviewed_by"] = "maintainer"
        for section, result in (("platforms", "passed"), ("licenses", "approved")):
            for rows in self.acceptance[section].values():
                for row in rows.values():
                    row.update(result=result, evidence="https://example.org/evidence/candidate")

    def rehash(self):
        (self.root / "SHA256SUMS").write_text(checksums(self.root))

    def check(self):
        return gate.verify_acceptance(self.root, REPO, TAG, self.acceptance)

    def test_real_cli_accepts_complete_evidence_and_rejects_a_changed_download(self):
        evidence = Path(self.temp.name) / "acceptance.json"
        gate.write(evidence, self.acceptance)
        args = [sys.executable, str(ROOT / "packaging/release_gate.py"), "check", str(self.root), TAG,
                "--repository", REPO, "--acceptance", str(evidence)]
        passed = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        (self.root / "badshop.deb").write_bytes(b"replaced bytes")
        failed = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Release bytes differ", failed.stderr)

    def test_pending_or_skipped_platform_result_and_missing_platform_are_refused(self):
        row = self.acceptance["platforms"]["windows-x64"]["signed_upgrade"]
        for result in ("pending", "skipped", "failed"):
            row["result"] = result
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "passing evidence"):
                self.check()
        row["result"] = "passed"
        del self.acceptance["platforms"]["macos-x64"]
        with self.assertRaisesRegex(ValueError, "every supported platform"):
            self.check()

    def test_inventory_with_pending_legal_reviews_cannot_be_promoted(self):
        self.acceptance["licenses"]["linux-x64"]["pkg:cargo/example@1"]["result"] = "pending"
        with self.assertRaisesRegex(ValueError, "passing evidence"):
            self.check()
        self.acceptance["licenses"]["linux-x64"] = {}
        with self.assertRaisesRegex(ValueError, "Unresolved or stale license"):
            self.check()

    def test_approval_cannot_be_reused_for_rebuilt_bytes_or_another_revision(self):
        self.acceptance["source_sha"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "identify these candidate bytes"):
            self.check()
        self.acceptance["source_sha"] = SHA
        (self.root / "badshop.deb").write_bytes(b"new build")
        self.rehash()
        with self.assertRaisesRegex(ValueError, "identify these candidate bytes"):
            self.check()

    def test_changed_inventory_and_update_destinations_are_refused(self):
        file = self.root / "badshop-linux-x64/badshop-linux-x64.licenses.json"
        value = gate.read(file)
        value["packages_without_notice_files"] = ["pkg:missing@1"]
        gate.write(file, value)
        self.rehash()
        with self.assertRaisesRegex(ValueError, "incomplete license"):
            self.check()
        value["packages_without_notice_files"] = []
        gate.write(file, value)
        feed = gate.read(self.root / "latest.json")
        feed["platforms"]["linux-x86_64"]["url"] = "https://example.org/other.AppImage"
        gate.write(self.root / "latest.json", feed)
        self.rehash()
        with self.assertRaisesRegex(ValueError, "outside this candidate"):
            self.check()

    def test_unsigned_os_disclosure_does_not_waive_updater_signature_checks(self):
        self.acceptance["platforms"]["windows-x64"]["os_trust"]["result"] = "unsigned-disclosed"
        self.check()
        self.acceptance["platforms"]["windows-x64"]["tampered_update"]["result"] = "unsigned-disclosed"
        with self.assertRaisesRegex(ValueError, "passing evidence"):
            self.check()

    def test_nightly_requires_the_same_acceptance_and_matching_build_attempt(self):
        tag = "nightly-20261112-123-1"
        gate.write(self.root / "latest.json", manifest(self.root, tag, REPO, "1.2.3-nightly.123"))
        gate.stage(self.root, tag, SHA, 123, 1)
        self.rehash()
        record = gate.acceptance_template(self.root, REPO, tag)
        self.assertEqual(set(record["platforms"]), set(self.acceptance["platforms"]))
        with self.assertRaises(ValueError):
            gate.verify_acceptance(self.root, REPO, tag, record)
        with self.assertRaisesRegex(ValueError, "this build attempt"):
            gate.stage(self.root, tag, SHA, 123, 2)

    def github_fixture(self):
        value = self.check()
        release = {"id": 5, "draft": True, "prerelease": False, "target_commitish": SHA, "assets": [
            {"name": name, "state": "uploaded", "digest": "sha256:" + gate.sha256(path)}
            for name, path in gate.assets(self.root).items()]}
        def api(*args):
            endpoint = args[1]
            if "/actions/workflows/" in endpoint:
                workflow = endpoint.split("/actions/workflows/")[1].split("/")[0]
                return {"workflow_runs": [{"head_sha": SHA, "head_branch": "main", "event": "push",
                        "path": f".github/workflows/{workflow}", "status": "completed", "conclusion": "success"}]}
            if "/actions/runs/" in endpoint:
                return {"head_sha": SHA, "path": ".github/workflows/release.yml", "status": "completed",
                        "conclusion": "success", "run_attempt": 1, "head_branch": TAG, "event": "push"}
            if "/matching-refs/" in endpoint:
                return [{"ref": f"refs/tags/{TAG}", "object": {"type": "commit", "sha": SHA}}]
            return copy.deepcopy(release)
        return value, release, api

    def test_github_requires_passing_main_checks_provenance_and_current_asset_digests(self):
        value, release, api = self.github_fixture()
        with patch.object(gate, "gh_json", side_effect=api), patch.object(gate.subprocess, "run") as run:
            gate.verify_github(self.root, REPO, value)
            self.assertEqual(run.call_args_list[0].args[0][-2:], [SHA, "origin/main"])
            attestation = run.call_args_list[1].args[0]
            self.assertIn("--source-digest", attestation)
            self.assertIn(f"{REPO}/.github/workflows/release.yml", attestation)
            release["assets"][0]["digest"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ValueError, "Draft bytes changed"):
                gate.verify_github(self.root, REPO, value)
        def failed_api(*args):
            result = api(*args)
            if "/maintenance.yml/" in args[1]:
                result["workflow_runs"][0]["conclusion"] = "failure"
            return result
        with patch.object(gate, "gh_json", side_effect=failed_api), patch.object(gate.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "successful main run: maintenance"):
                gate.verify_github(self.root, REPO, value)

    def test_publication_mutation_occurs_only_after_acceptance_and_supports_safe_retry(self):
        _, release, api = self.github_fixture()
        evidence = Path(self.temp.name) / "acceptance.json"
        gate.write(evidence, self.acceptance)
        args = ["release_gate", "publish", str(self.root), TAG, "--repository", REPO, "--acceptance", str(evidence)]
        env = {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch"}
        with patch("sys.argv", args), patch.dict(os.environ, env), patch.object(gate.subprocess, "run"):
            with patch.object(gate, "gh_json", side_effect=api) as calls:
                gate.main()
                writes = [call for call in calls.call_args_list if "PATCH" in call.args]
                self.assertEqual(len(writes), 1)
                self.assertIn("draft=false", writes[0].args)
            release["draft"] = False
            with patch.object(gate, "gh_json", side_effect=api) as calls:
                gate.main()
                self.assertFalse(any("PATCH" in call.args for call in calls.call_args_list))
            self.acceptance["licenses"]["macos-x64"] = {}
            gate.write(evidence, self.acceptance)
            with patch.object(gate, "gh_json") as calls:
                with self.assertRaisesRegex(ValueError, "Unresolved or stale"):
                    gate.main()
                calls.assert_not_called()

    def test_real_git_rejects_source_outside_main_before_querying_github(self):
        repo = Path(self.temp.name) / "git"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.STDOUT)
        git("init")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("commit", "--allow-empty", "-m", "main")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        git("commit", "--allow-empty", "-m", "not merged")
        source = git("rev-parse", "HEAD").decode().strip()
        with patch.object(gate, "ROOT", repo), patch.object(gate, "gh_json") as api:
            with self.assertRaises(subprocess.CalledProcessError):
                gate.verify_source(REPO, source)
            api.assert_not_called()

    def test_failed_attestation_or_wrong_build_attempt_prevents_publication(self):
        value, _, api = self.github_fixture()
        def wrong_attempt(*args):
            result = api(*args)
            if "/actions/runs/" in args[1]:
                result["run_attempt"] = 2
            return result
        with patch.object(gate, "gh_json", side_effect=wrong_attempt), patch.object(gate.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "build run did not pass"):
                gate.verify_github(self.root, REPO, value)
        with patch.object(gate, "gh_json", side_effect=api), patch.object(
                gate.subprocess, "run", side_effect=[None, subprocess.CalledProcessError(1, "gh attestation")]):
            with self.assertRaises(subprocess.CalledProcessError):
                gate.verify_github(self.root, REPO, value)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_staging_refuses_published_assets_and_does_not_hide_api_failures(self):
        def response(code, value):
            return subprocess.CompletedProcess(["gh"], code, json.dumps(value), "API failure" if code else "")
        with patch.object(gate.subprocess, "run", return_value=response(0, {"draft": False})):
            with self.assertRaisesRegex(ValueError, "already published"):
                gate.require_unpublished(REPO, TAG)
        with patch.object(gate.subprocess, "run", return_value=response(1, {"status": "403"})):
            with self.assertRaisesRegex(RuntimeError, "Cannot inspect"):
                gate.require_unpublished(REPO, TAG)
        with patch.object(gate.subprocess, "run", return_value=response(1, {"status": "404"})):
            gate.require_unpublished(REPO, TAG)

    def test_build_workflows_leave_candidates_unpublished(self):
        for name in ("nightly.yml", "release.yml"):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
                self.assertNotIn("--draft=false", workflow)
                self.assertNotIn("pypi-publish@", workflow)
                self.assertNotIn("tag_name: nightly\n", workflow)


if __name__ == "__main__":
    unittest.main()
