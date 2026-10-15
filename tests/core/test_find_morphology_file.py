import tempfile
import unittest
from pathlib import Path

from app.infrastructure.storage import find_morphology_file


class TestFindMorphologyFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _touch(self, *parts: str) -> Path:
        path = self.dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def test_flat_file(self):
        expected = self._touch("cell.asc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_per_format_subdirs_prefer_asc(self):
        self._touch("swc", "cell.swc")
        self._touch("h5", "cell.h5")
        expected = self._touch("asc", "cell.asc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_falls_back_to_swc_then_h5(self):
        self._touch("h5", "cell.h5")
        expected = self._touch("swc", "cell.swc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_h5_only(self):
        expected = self._touch("h5", "cell.h5")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_never_returns_a_directory(self):
        (self.dir / "asc").mkdir()
        expected = self._touch("swc", "cell.swc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_empty_dir_raises(self):
        with self.assertRaises(FileNotFoundError):
            find_morphology_file(self.dir)

    def test_flat_dir_prefers_format_over_alphabetical_order(self):
        self._touch("cell.h5")
        expected = self._touch("cell.swc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_ignores_files_without_a_morphology_extension(self):
        self._touch(".DS_Store")
        self._touch("cell.asc.part")
        self._touch("notes.txt")
        expected = self._touch("cell.swc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_only_unknown_extensions_raises(self):
        self._touch(".DS_Store")
        self._touch("asc", "notes.txt")

        with self.assertRaises(FileNotFoundError):
            find_morphology_file(self.dir)

    def test_upper_case_extension_flat(self):
        expected = self._touch("CELL.ASC")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_upper_case_extension_in_subdir(self):
        self._touch("swc", "cell.swc")
        expected = self._touch("asc", "Cell.Asc")

        self.assertEqual(find_morphology_file(self.dir), expected)

    def test_upper_case_extension_counts_for_preference(self):
        self._touch("cell.H5")
        expected = self._touch("cell.SWC")

        self.assertEqual(find_morphology_file(self.dir), expected)
