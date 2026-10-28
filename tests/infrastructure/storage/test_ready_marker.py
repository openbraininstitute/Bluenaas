import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.infrastructure.storage import clear_stale, is_ready, mark_ready


class TestReadyMarker(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.path)

    def test_not_ready_without_marker(self):
        self.assertFalse(is_ready(self.path))

    def test_ready_after_mark(self):
        mark_ready(self.path)
        self.assertTrue(is_ready(self.path))

    def test_marker_from_an_older_version_is_not_ready(self):
        (self.path / READY_MARKER_FILE_NAME).write_text("1")
        self.assertFalse(is_ready(self.path))

    def test_empty_legacy_marker_is_not_ready(self):
        (self.path / READY_MARKER_FILE_NAME).touch()
        self.assertFalse(is_ready(self.path))


class TestClearStale(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.path)

    def test_removes_stale_content_but_keeps_the_lock(self):
        (self.path / DIR_LOCK_FILE_NAME).touch()
        (self.path / READY_MARKER_FILE_NAME).touch()
        (self.path / "x86_64" / "lib").mkdir(parents=True)
        (self.path / "x86_64" / "lib" / "nrnmech.so").write_text("old build")
        (self.path / "mechanisms").mkdir()
        (self.path / "mechanisms" / "VecStim.mod").write_text("old")

        clear_stale(self.path)

        self.assertEqual([p.name for p in self.path.iterdir()], [DIR_LOCK_FILE_NAME])

    def test_empty_directory_is_a_noop(self):
        clear_stale(self.path)
        self.assertEqual(list(self.path.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
