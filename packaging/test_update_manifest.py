import tempfile
import unittest
from pathlib import Path
from update_manifest import TARGETS, manifest


class UpdateManifestTests(unittest.TestCase):
    def test_feed_points_at_each_signed_artifact_and_refuses_missing_signatures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, (_, suffix) in TARGETS.items():
                folder = root / f"badshop-{label}"
                folder.mkdir()
                artifact = folder / f"badshop-{label}{suffix}"
                artifact.write_bytes(b"release fixture")
                signature = Path(str(artifact) + ".sig")
                signature.write_text(f"signature-{label}\n")
            feed = manifest(root, "v0.3.0", "owner/repo")
            self.assertEqual(feed["version"], "0.3.0")
            self.assertEqual(set(feed["platforms"]), {target for target, _ in TARGETS.values()})
            for label, (target, suffix) in TARGETS.items():
                self.assertEqual(feed["platforms"][target], {
                    "signature": f"signature-{label}",
                    "url": f"https://github.com/owner/repo/releases/download/v0.3.0/badshop-{label}{suffix}",
                })
            signature.unlink()
            with self.assertRaises(FileNotFoundError):
                manifest(root, "v0.3.0", "owner/repo")


if __name__ == "__main__":
    unittest.main()
