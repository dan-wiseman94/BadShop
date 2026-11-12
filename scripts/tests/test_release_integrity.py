"""Release integrity must cover every uploaded asset and reject ambiguous names."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
from release_checksums import checksums
from check_version import check_versions
from release_inventory import command
from update_manifest import can_promote_nightly, manifest, nightly_version


class ReleaseIntegrityTests(unittest.TestCase):
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
        self.assertIn("needs: [core, frontend, bundle, security]", workflow)
        self.assertIn("needs: [core, frontend, bundle, security, publish-installers]", workflow)
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
        self.assertIn("secrets: inherit", workflow)
        self.assertIn("target_commitish: ${{ github.sha }}", workflow)
        self.assertIn("${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}", workflow)
        publish = workflow.split("  publish:", 1)[1]
        self.assertIn("id: identity", publish)
        self.assertIn("tag_name: ${{ steps.identity.outputs.tag }}", publish)
        self.assertIn("packaging/release_checksums.py artifacts", workflow)
        self.assertIn("actions/attest-build-provenance@", workflow)
        self.assertIn("draft: true", workflow)
        self.assertIn("prerelease: true", workflow)
        self.assertIn("make_latest: 'false'", workflow)
        self.assertIn('--draft=false --prerelease --latest=false', workflow)
        self.assertIn('packaging/update_manifest.py artifacts', workflow)
        self.assertLess(workflow.index('--draft=false --prerelease --latest=false'), workflow.index('tag_name: nightly'))
        self.assertNotIn("pypi-publish", workflow)
        core = (root / ".github/workflows/core.yml").read_text()
        self.assertIn("group: core-${{ github.workflow }}-", core)
        native = (root / ".github/workflows/native-desktop.yml").read_text()
        self.assertIn("ref: ${{ inputs.source_ref || github.sha }}", native)
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
