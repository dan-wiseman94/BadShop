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
