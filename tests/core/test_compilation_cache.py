import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.compilation_cache import compile_with_cache, compute_mod_hash


class TestComputeModHash(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.mod_dir = self.tmpdir / "mechanisms"
        self.mod_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_deterministic_hash(self):
        (self.mod_dir / "A.mod").write_text("content A")
        (self.mod_dir / "B.mod").write_text("content B")

        hash1 = compute_mod_hash(self.mod_dir)
        hash2 = compute_mod_hash(self.mod_dir)
        self.assertEqual(hash1, hash2)

    def test_different_content_different_hash(self):
        (self.mod_dir / "A.mod").write_text("content A")
        hash1 = compute_mod_hash(self.mod_dir)

        (self.mod_dir / "A.mod").write_text("content B")
        hash2 = compute_mod_hash(self.mod_dir)

        self.assertNotEqual(hash1, hash2)

    def test_different_filenames_different_hash(self):
        (self.mod_dir / "A.mod").write_text("same content")
        hash1 = compute_mod_hash(self.mod_dir)

        (self.mod_dir / "A.mod").unlink()
        (self.mod_dir / "B.mod").write_text("same content")
        hash2 = compute_mod_hash(self.mod_dir)

        self.assertNotEqual(hash1, hash2)

    def test_order_independent(self):
        """Hash should be the same regardless of file creation order."""
        (self.mod_dir / "B.mod").write_text("content B")
        (self.mod_dir / "A.mod").write_text("content A")
        hash1 = compute_mod_hash(self.mod_dir)

        shutil.rmtree(self.mod_dir)
        self.mod_dir.mkdir()
        (self.mod_dir / "A.mod").write_text("content A")
        (self.mod_dir / "B.mod").write_text("content B")
        hash2 = compute_mod_hash(self.mod_dir)

        self.assertEqual(hash1, hash2)

    def test_no_mod_files_raises(self):
        with self.assertRaises(FileNotFoundError):
            compute_mod_hash(self.mod_dir)


class TestCompileWithCache(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.storage_path = self.tmpdir / "storage"
        self.storage_path.mkdir()

        self.model_path = self.tmpdir / "model"
        self.model_path.mkdir()
        self.mod_dir = self.model_path / "mechanisms"
        self.mod_dir.mkdir()
        (self.mod_dir / "test.mod").write_text("NEURON { SUFFIX test }")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_skips_if_already_compiled(self):
        compiled = self.model_path / "x86_64"
        compiled.mkdir()

        with patch("app.core.compilation_cache.subprocess") as mock_sub:
            compile_with_cache(self.model_path, "mechanisms")
            mock_sub.check_output.assert_not_called()

    @patch("app.core.compilation_cache.settings")
    @patch("app.core.compilation_cache.subprocess")
    def test_cache_miss_compiles_and_caches(self, mock_sub, mock_settings):
        mock_settings.STORAGE_PATH = self.storage_path

        def fake_compile(cmd, cwd, text=False):
            (cwd / "x86_64" / "lib").mkdir(parents=True)
            (cwd / "x86_64" / "lib" / "nrnmech.so").write_text("compiled")
            return "compilation output"

        mock_sub.check_output.side_effect = fake_compile

        compile_with_cache(self.model_path, "mechanisms")

        mock_sub.check_output.assert_called_once()
        self.assertTrue((self.model_path / "x86_64" / "lib" / "nrnmech.so").exists())

        # Verify cache was populated
        cache_base = self.storage_path / "compilation-cache"
        self.assertTrue(cache_base.exists())

    @patch("app.core.compilation_cache.settings")
    @patch("app.core.compilation_cache.subprocess")
    def test_cache_hit_skips_compilation(self, mock_sub, mock_settings):
        mock_settings.STORAGE_PATH = self.storage_path

        def fake_compile(cmd, cwd, text=False):
            (cwd / "x86_64" / "lib").mkdir(parents=True)
            (cwd / "x86_64" / "lib" / "nrnmech.so").write_text("compiled")
            return "compilation output"

        mock_sub.check_output.side_effect = fake_compile

        # First call: cache miss, compiles
        compile_with_cache(self.model_path, "mechanisms")
        self.assertEqual(mock_sub.check_output.call_count, 1)

        # Remove compiled output from model path to simulate a second model
        shutil.rmtree(self.model_path / "x86_64")

        # Second call: cache hit, should not compile again
        compile_with_cache(self.model_path, "mechanisms")
        self.assertEqual(mock_sub.check_output.call_count, 1)  # Still 1
        self.assertTrue((self.model_path / "x86_64" / "lib" / "nrnmech.so").exists())

    def test_missing_mod_dir_raises(self):
        empty_path = self.tmpdir / "empty"
        empty_path.mkdir()

        with self.assertRaises(FileNotFoundError):
            compile_with_cache(empty_path, "mechanisms")


if __name__ == "__main__":
    unittest.main()
