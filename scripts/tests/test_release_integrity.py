"""Release integrity must cover every uploaded asset and reject ambiguous names."""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
from check_version import check_versions
from release_checksums import checksums
from release_inventory import command
from update_manifest import can_promote_nightly, manifest, nightly_version


class ReleaseIntegrityTests(unittest.TestCase):
    def test_signing_uses_only_the_authorized_workflow_event_commit(self):
        workflows = Path(__file__).resolve().parents[2] / '.github/workflows'
        native = (workflows / 'native-desktop.yml').read_text(encoding='utf-8')
        triggers, jobs = native.split('\njobs:\n', 1)
        self.assertNotIn('\n  workflow_dispatch:', triggers)
        self.assertNotIn('source_ref', native)
        signing_secrets = (
            "TAURI_SIGNING_PRIVATE_KEY",
            "TAURI_SIGNING_PRIVATE_KEY_PASSWORD",
        )
        declared = triggers.split("\n    secrets:\n", 1)[1].split("\n    inputs:", 1)[0]
        self.assertEqual(declared, "\n".join(f"      {name}:\n        required: false" for name in signing_secrets))
        guard, steps = jobs.split('\n    steps:\n', 1)
        self.assertIn("environment: ${{ inputs.nightly && 'updater-signing-nightly' || 'updater-signing-stable' }}", guard)
        self.assertIn('github.ref_protected', guard)
        self.assertIn("github.event_name == 'push'", guard)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", guard)
        self.assertIn('/.github/workflows/release.yml@', guard)
        self.assertIn("github.event_name == 'schedule'", guard)
        self.assertIn("github.ref == 'refs/heads/main'", guard)
        self.assertIn('/.github/workflows/nightly.yml@', guard)
        self.assertIn('ref: ${{ github.sha }}', steps)
        self.assertIn('TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}', steps)
        for filename in ('release.yml', 'nightly.yml'):
            with self.subTest(filename=filename):
                caller = (workflows / filename).read_text(encoding='utf-8')
                self.assertIn('uses: ./.github/workflows/native-desktop.yml', caller)
                self.assertNotIn('secrets: inherit', caller)
                call = caller.split('uses: ./.github/workflows/native-desktop.yml', 1)[1]
                job = call.split('\n  stage-', 1)[0]
                if filename == 'release.yml':
                    self.assertEqual(job, "\n    secrets:\n" + "\n".join(
                        f"      {name}: ${{{{ secrets.{name} }}}}" for name in signing_secrets
                    ))
                else:
                    self.assertNotIn('secrets:', job)

    def test_candidate_draft_access_does_not_raise_reusable_builder_permissions(self):
        root = Path(__file__).resolve().parents[2]
        native = (root / '.github/workflows/native-desktop.yml').read_text()
        candidate = (root / '.github/workflows/accept-candidate.yml').read_text()
        self.assertNotIn('contents: write', native)
        self.assertIn('contents: write', candidate)
        self.assertNotIn('workflow_call:', candidate)
        self.assertIn('packaging/accept_candidate.py', candidate)

    def test_inventory_decodes_utf8_package_metadata_on_every_host(self):
        value = command(sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes.fromhex('7b226e616d65223a2022e69687e5ad97227d'))")
        self.assertEqual(value, {"name": "\u6587\u5b57"})

    def test_version_gate_rejects_wrong_tag_or_platform_metadata(self):
        root = Path(__file__).resolve().parents[2]
        version = check_versions(root)
        self.assertEqual(check_versions(root, f"v{version}"), version)
        with self.assertRaisesRegex(ValueError, "release tag"):
            check_versions(root, "v999.0.0")
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp)
            for name in ("core/pyproject.toml", "core/uv.lock", "core/src/badshop/__init__.py",
                         "app/package.json", "app/src-tauri/Cargo.toml", "app/src-tauri/Cargo.lock",
                         "app/src-tauri/tauri.conf.json"):
                target = copy / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, target)
            config = copy / "app/src-tauri/tauri.conf.json"
            value = json.loads(config.read_text())
            value["version"] = "999.0.0"
            config.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "tauri.conf.json"):
                check_versions(copy, f"v{version}")

    def test_exact_bytes_and_unique_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "no release assets"):
                checksums(root)
            (root / "linux").mkdir()
            (root / "linux" / "badshop.deb").write_bytes(b"installer bytes")
            (root / "latest.json").write_bytes(b"signed update manifest")
            (root / "SHA256SUMS").write_text("old checksum must not hash itself")
            result = checksums(root)
            self.assertEqual(set(result.splitlines()), {
                hashlib.sha256(b"installer bytes").hexdigest() + "  badshop.deb",
                hashlib.sha256(b"signed update manifest").hexdigest() + "  latest.json",
            })
            (root / "badshop.deb").write_bytes(b"different platform, same name")
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                checksums(root)

    def test_release_waits_for_exact_lock_security_and_attests_assets(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/release.yml").read_text()
        self.assertIn("needs: [source, core, frontend, bundle, security]", workflow)
        self.assertIn('git merge-base --is-ancestor "$GITHUB_SHA" origin/main', workflow)
        self.assertIn("packaging/release_gate.py stage", workflow)
        self.assertIn("packaging/release_checksums.py artifacts", workflow)
        self.assertIn("actions/attest-build-provenance@", workflow)
        self.assertIn("draft: true", workflow)

    def test_nightly_publication_is_gated_and_isolated_from_stable(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/nightly.yml").read_text()
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("needs: [prepare, core, frontend, bundle, security]", workflow)
        self.assertIn("full: true", workflow)
        self.assertIn("uses: ./.github/workflows/native-desktop.yml", workflow)
        self.assertIn("nightly: true", workflow)
        self.assertIn("target_commitish: ${{ github.sha }}", workflow)
        self.assertIn("${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}", workflow)
        publish = workflow.split("  stage:", 1)[1]
        self.assertIn("id: identity", publish)
        self.assertIn("tag_name: ${{ steps.identity.outputs.tag }}", publish)
        self.assertIn("packaging/release_checksums.py artifacts", workflow)
        self.assertIn("actions/attest-build-provenance@", workflow)
        self.assertIn("draft: true", workflow)
        self.assertIn("prerelease: true", workflow)
        self.assertIn("make_latest: 'false'", workflow)
        promotion = (root / ".github/workflows/promote-release.yml").read_text()
        self.assertIn("environment: release", promotion)
        self.assertIn("packaging/release_gate.py publish", promotion)
        self.assertIn("environment: pypi", promotion)
        self.assertIn("needs: publish", promotion)
        self.assertIn('packaging/update_manifest.py artifacts', workflow)
        self.assertLess(promotion.index("packaging/release_gate.py publish"), promotion.index("tag_name: nightly"))
        self.assertNotIn("pypi-publish", workflow)
        core = (root / ".github/workflows/core.yml").read_text()
        self.assertIn("group: core-${{ github.workflow }}-", core)
        native = (root / ".github/workflows/native-desktop.yml").read_text()
        build = native.split("- name: Build native installers", 1)[1].split("- name:", 1)[0]
        self.assertIn("BADSHOP_UPDATER_PUBLIC_KEY: ${{ vars.BADSHOP_UPDATER_PUBLIC_KEY }}", build)

    def test_nightly_manifest_links_signed_immutable_artifacts_and_orders_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for label, filename in (("linux-x64", "badshop.AppImage"), ("windows-x64", "badshop.exe"),
                                    ("macos-arm64", "badshop-arm.app.tar.gz"), ("macos-x64", "badshop-x64.app.tar.gz")):
                folder = root / f"badshop-{label}"
                folder.mkdir()
                (folder / filename).write_bytes(b"packaged application")
                (folder / (filename + ".sig")).write_text("signed-payload")
            version = nightly_version("0.4.2", "123")
            feed = manifest(root, "nightly-20261112-123-1", "owner/repo", version)
            self.assertEqual(feed["version"], "0.4.2-nightly.123")
            self.assertEqual(len(feed["platforms"]), 4)
            self.assertTrue(all('/download/nightly-20261112-123-1/' in p['url']
                                and p['signature'] == 'signed-payload' for p in feed['platforms'].values()))
            self.assertTrue(can_promote_nightly({"version": "0.4.2-nightly.122"}, feed))
            self.assertFalse(can_promote_nightly(feed, feed))
            self.assertFalse(can_promote_nightly({"version": "0.4.3-nightly.124"}, feed))
            (root / "badshop-linux-x64/badshop.AppImage.sig").unlink()
            with self.assertRaises(FileNotFoundError):
                manifest(root, "nightly-123", "owner/repo", version)

    def test_nightly_version_rejects_ambiguous_or_invalid_identifiers(self):
        for base, run in (("0.4.2-beta.1", "123"), ("0.4.2", "01"), ("0.4.2", "x")):
            with self.subTest(base=base, run=run), self.assertRaises(ValueError):
                nightly_version(base, run)

    def test_missing_nightly_feed_can_be_repaired_without_rolling_back(self):
        previous = {"version": "0.4.3-nightly.200"}
        self.assertFalse(can_promote_nightly(previous, {"version": "0.4.2-nightly.100"}, feed_missing=True))
        self.assertTrue(can_promote_nightly(previous, previous, feed_missing=True))
        self.assertFalse(can_promote_nightly(previous, previous))
