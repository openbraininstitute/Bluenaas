import os
import platform
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.compilation_cache import (
    compile_with_cache,
    compute_cache_key,
    compute_mod_hash,
)

ARCH = platform.machine()


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


class TestComputeCacheKey(unittest.TestCase):
    """The cache key covers the model MODs, BlueCelluLab's bundled MODs, the
    compiler flags and the NEURON version."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.mod_dir = self.tmpdir / "mechanisms"
        self.mod_dir.mkdir()
        (self.mod_dir / "A.mod").write_text("model content")
        self.bundled_dir = self.tmpdir / "bundled"
        self.bundled_dir.mkdir()
        (self.bundled_dir / "vecevent.mod").write_text("bundled content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def key(self, mod_dir=None, bundled_dir=None, incflags="-DDISABLE_REPORTINGLIB", nrn="9.0.0"):
        return compute_cache_key(
            mod_dir or self.mod_dir, bundled_dir or self.bundled_dir, incflags, nrn
        )

    def test_deterministic(self):
        self.assertEqual(self.key(), self.key())

    def test_model_mod_change_changes_key(self):
        key1 = self.key()
        (self.mod_dir / "A.mod").write_text("changed")
        self.assertNotEqual(key1, self.key())

    def test_bundled_mod_change_changes_key(self):
        key1 = self.key()
        (self.bundled_dir / "vecevent.mod").write_text("changed")
        self.assertNotEqual(key1, self.key())

    def test_neuron_version_change_changes_key(self):
        self.assertNotEqual(self.key(), self.key(nrn="9.0.1"))

    def test_incflags_change_changes_key(self):
        self.assertNotEqual(self.key(), self.key(incflags="-DOTHER"))

    def test_missing_mod_dir_still_keys(self):
        missing = self.tmpdir / "absent"
        self.assertEqual(self.key(mod_dir=missing), self.key(mod_dir=missing))

    def test_empty_mod_dir_still_keys(self):
        empty = self.tmpdir / "empty"
        empty.mkdir()
        self.assertEqual(self.key(mod_dir=empty), self.key(mod_dir=empty))


class TestCompileWithCache(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.storage_path = self.tmpdir / "storage"
        self.storage_path.mkdir()

        self.bundled_dir = self.tmpdir / "bundled"
        self.bundled_dir.mkdir()
        (self.bundled_dir / "vecevent.mod").write_text("bundled")

        self.model_path = self.tmpdir / "model"
        self.model_path.mkdir()
        self.mod_dir = self.model_path / "mechanisms"
        self.mod_dir.mkdir()
        (self.mod_dir / "test.mod").write_text("NEURON { SUFFIX test }")

        self.cache_inputs = patch(
            "app.core.compilation_cache._bcl_cache_inputs",
            return_value=(self.bundled_dir, "-DDISABLE_REPORTINGLIB", "9.0.0"),
        )
        self.bcl_inputs = self.cache_inputs.start()

        self.bcl_compile = patch("app.core.compilation_cache._bcl_compile_mods").start()
        self.bcl_compile.side_effect = self._fake_compile

        patch("app.infrastructure.storage.current_epoch", new=lambda kind: "e" * 32).start()
        self.settings = patch("app.infrastructure.storage.settings").start()
        self.settings.STORAGE_PATH = self.storage_path

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir)

    @staticmethod
    def _fake_compile(input_dirs, output_dir):
        lib = output_dir / ARCH / "lib"
        lib.mkdir(parents=True)
        nrnmech = lib / "nrnmech.so"
        nrnmech.write_text("compiled")
        return nrnmech

    def test_skips_if_already_compiled(self):
        (self.model_path / ARCH).mkdir()

        compile_with_cache(self.model_path, "mechanisms")

        self.bcl_compile.assert_not_called()

    def test_cache_miss_compiles_and_caches(self):
        compile_with_cache(self.model_path, "mechanisms")

        self.bcl_compile.assert_called_once()
        input_dirs, output_dir = self.bcl_compile.call_args.args
        self.assertEqual(input_dirs, [self.mod_dir])
        self.assertTrue(output_dir.is_relative_to(self.storage_path))
        self.assertTrue((self.model_path / ARCH / "lib" / "nrnmech.so").exists())
        self.assertTrue((self.storage_path / "compilation").exists())

    def test_cache_hit_skips_compilation(self):
        compile_with_cache(self.model_path, "mechanisms")
        self.assertEqual(self.bcl_compile.call_count, 1)

        # Remove compiled output to simulate a second, identical model.
        shutil.rmtree(self.model_path / ARCH)

        compile_with_cache(self.model_path, "mechanisms")
        self.assertEqual(self.bcl_compile.call_count, 1)
        self.assertTrue((self.model_path / ARCH / "lib" / "nrnmech.so").exists())

    def test_missing_mod_dir_compiles_bundled_only(self):
        """A passive model gets the bundled mechanisms compiled anyway."""
        model_path = self.tmpdir / "no_mechanisms"
        model_path.mkdir()

        compile_with_cache(model_path, "mechanisms")

        self.bcl_compile.assert_called_once()
        input_dirs, _ = self.bcl_compile.call_args.args
        self.assertEqual(input_dirs, [])
        self.assertTrue((model_path / ARCH / "lib" / "nrnmech.so").exists())

    def test_empty_mod_dir_compiles_bundled(self):
        model_path = self.tmpdir / "empty_mechanisms"
        (model_path / "mechanisms").mkdir(parents=True)

        compile_with_cache(model_path, "mechanisms")

        self.bcl_compile.assert_called_once()
        input_dirs, _ = self.bcl_compile.call_args.args
        self.assertEqual(input_dirs, [model_path / "mechanisms"])
        self.assertTrue((model_path / ARCH / "lib" / "nrnmech.so").exists())


if __name__ == "__main__":
    unittest.main()
