"""Artifact cache contracts, with download responses stubbed in memory."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).resolve().parents[2] / "docker/scripts/fetch_artifacts.py"
spec = importlib.util.spec_from_file_location("fetch_artifacts", SCRIPT)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class ArtifactCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = b"verified artifact"
        self.item = {"path": "models/model.bin", "url": "https://example.test/model.bin",
                     "size": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}

    def write(self, data):
        path = self.root / self.item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_existing_valid_file_never_uses_network(self):
        path = self.write(self.data)
        before = path.stat().st_mtime_ns
        with patch.object(cache.urllib.request, "urlopen") as download:
            cache.ensure_file(self.root, self.item)
        download.assert_not_called()
        self.assertEqual(before, path.stat().st_mtime_ns)

    def test_corrupt_file_is_replaced_after_verification(self):
        path = self.write(b"partial")
        with patch.object(cache.urllib.request, "urlopen", return_value=io.BytesIO(self.data)):
            cache.ensure_file(self.root, self.item)
        self.assertEqual(path.read_bytes(), self.data)
        self.assertFalse(list(path.parent.glob("*.part")))

    def test_bad_download_does_not_replace_existing_file(self):
        path = self.write(b"old")
        with patch.object(cache.urllib.request, "urlopen", side_effect=lambda *a, **kw: io.BytesIO(b"wrong")), patch.object(cache.time, "sleep"):
            with self.assertRaises(ValueError):
                cache.ensure_file(self.root, self.item)
        self.assertEqual(path.read_bytes(), b"old")
        self.assertFalse(list(path.parent.glob("*.part")))

    def test_offline_check_rejects_missing_file_without_network(self):
        with patch.object(cache.urllib.request, "urlopen") as download:
            with self.assertRaises(ValueError):
                cache.ensure_file(self.root, self.item, offline=True)
        download.assert_not_called()

    def nltk(self, member="punkt/data.txt"):
        archive = self.root / "punkt.zip"
        with zipfile.ZipFile(archive, "w") as out:
            out.writestr(member, self.data)
        return {"path": "punkt.zip", "sha256": cache.digest(archive),
                "extract_to": "nltk_data/tokenizers", "extracted_root": "punkt"}

    def test_incomplete_extraction_is_repaired_from_cache(self):
        item = self.nltk()
        cache.extract_nltk(self.root, item)
        target = self.root / "nltk_data/tokenizers/punkt/data.txt"
        target.unlink()
        with self.assertRaises(ValueError):
            cache.extract_nltk(self.root, item, offline=True)
        cache.extract_nltk(self.root, item)
        self.assertEqual(target.read_bytes(), self.data)
        cache.extract_nltk(self.root, item, offline=True)

    def test_archive_cannot_escape_cache(self):
        item = self.nltk("../../../escaped.txt")
        with self.assertRaises(ValueError):
            cache.extract_nltk(self.root, item)

    def test_corrupt_extraction_receipt_is_rebuilt(self):
        item = self.nltk()
        cache.extract_nltk(self.root, item)
        (self.root / ".receipts/punkt.json").write_text("incomplete")
        cache.extract_nltk(self.root, item)
        cache.extract_nltk(self.root, item, offline=True)

    def test_manifest_pins_official_https_resources(self):
        manifest = json.loads(cache.MANIFEST.read_text(encoding="utf-8"))
        paths = [item["path"] for item in manifest["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        for item in manifest["files"]:
            self.assertTrue(item["url"].startswith("https://"))
            self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$")
            self.assertGreater(item["size"], 0)


if __name__ == "__main__":
    unittest.main()
