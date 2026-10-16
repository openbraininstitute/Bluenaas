import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.infrastructure.storage import (
    get_circuit_location,
    get_circuit_simulation_location,
    get_circuit_simulation_output_location,
    get_compatibility_result_location,
    get_ion_channel_build_location,
    get_mesh_location,
    get_model_candidate_location,
    get_single_neuron_location,
    get_single_neuron_validation_output_location,
    rm_dir_parallel,
)


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")
MORPH_ID_ALT = UUID("33333333-3333-3333-3333-333333333333")


EPOCH = "0123456789abcdef0123456789abcdef"
in_epoch = patch("app.infrastructure.storage.current_epoch", new=lambda kind: EPOCH)


@in_epoch
class TestLocationsAreInTheEpoch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Path(self._tmp.name)

        patcher = patch("app.infrastructure.storage.settings")
        patcher.start().STORAGE_PATH = self.storage
        self.addCleanup(patcher.stop)

    def test_locations(self):
        entry = "11111111-1111-1111-1111-111111111111"
        subpath = "1/1/111111-1111-1111-1111-111111111111"
        uuid = UUID(entry)
        e = f"e{EPOCH}"

        expected = {
            get_circuit_location(uuid): f"circuit/{e}/model/{subpath}",
            get_circuit_simulation_location(uuid): f"circuit/{e}/simulation/{subpath}",
            get_circuit_simulation_output_location(uuid): f"circuit/{e}/output/{subpath}",
            get_single_neuron_location(uuid): f"single-neuron/{e}/model/{subpath}",
            get_single_neuron_validation_output_location(uuid): (
                f"single-neuron/{e}/validation-output/{subpath}"
            ),
            get_mesh_location(uuid): f"mesh/{e}/mesh/{subpath}",
            get_ion_channel_build_location(uuid): f"ion-channel/{e}/build/{subpath}",
        }

        for path, relative in expected.items():
            with self.subTest(relative=relative):
                self.assertEqual(path, self.storage / relative)
                self.assertTrue(path.is_dir())

    def test_candidate_and_result_locations_are_in_the_epoch(self):
        e = f"e{EPOCH}"

        candidate = get_model_candidate_location(MORPH_ID, EMODEL_ID)
        result = get_compatibility_result_location(MORPH_ID, EMODEL_ID)

        self.assertEqual(
            candidate.relative_to(self.storage).parts[:3], ("single-neuron", e, "model-candidate")
        )
        self.assertEqual(
            result.relative_to(self.storage).parts[:3], ("single-neuron", e, "compatibility")
        )

    def test_a_new_epoch_means_new_locations(self):
        uuid = UUID("11111111-1111-1111-1111-111111111111")
        before = get_circuit_location(uuid)

        with patch("app.infrastructure.storage.current_epoch", new=lambda kind: "f" * 32):
            after = get_circuit_location(uuid)

        self.assertNotEqual(before, after)


@in_epoch
class TestCompatibilityLocations(unittest.TestCase):
    @patch("app.infrastructure.storage.settings")
    def test_model_candidate_deterministic(self, mock_settings):
        mock_settings.STORAGE_PATH = Path("/tmp/test-storage")
        path1 = get_model_candidate_location(MORPH_ID, EMODEL_ID)
        path2 = get_model_candidate_location(MORPH_ID, EMODEL_ID)
        self.assertEqual(path1, path2)

    @patch("app.infrastructure.storage.settings")
    def test_compatibility_result_deterministic(self, mock_settings):
        mock_settings.STORAGE_PATH = Path("/tmp/test-storage")
        path1 = get_compatibility_result_location(MORPH_ID, EMODEL_ID)
        path2 = get_compatibility_result_location(MORPH_ID, EMODEL_ID)
        self.assertEqual(path1, path2)

    @patch("app.infrastructure.storage.settings")
    def test_different_inputs_produce_different_paths(self, mock_settings):
        mock_settings.STORAGE_PATH = Path("/tmp/test-storage")
        path1 = get_model_candidate_location(MORPH_ID, EMODEL_ID)
        path2 = get_model_candidate_location(MORPH_ID_ALT, EMODEL_ID)
        self.assertNotEqual(path1, path2)

    @patch("app.infrastructure.storage.settings")
    def test_candidate_and_result_use_different_directories(self, mock_settings):
        mock_settings.STORAGE_PATH = Path("/tmp/test-storage")
        candidate_path = get_model_candidate_location(MORPH_ID, EMODEL_ID)
        result_path = get_compatibility_result_location(MORPH_ID, EMODEL_ID)
        self.assertNotEqual(candidate_path, result_path)
        self.assertIn("model-candidate", str(candidate_path))
        self.assertIn("compatibility", str(result_path))


class TestRmDirParallel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "tree"

    def build_tree(self, groups: int, entries: int) -> None:
        for g in range(groups):
            for e in range(entries):
                entry = self.root / "model" / f"{g}" / f"{g}" / f"entry-{e}" / "deep"
                entry.mkdir(parents=True)
                (entry / "data.bin").write_bytes(b"data")
            (self.root / "model" / f"{g}" / "stray-file").write_bytes(b"x")
        (self.root / ".retired").write_text("{}")

    def test_removes_the_whole_tree(self):
        self.build_tree(groups=5, entries=6)

        rm_dir_parallel(self.root, workers=4)

        self.assertFalse(self.root.exists())

    def test_removes_a_tree_too_small_to_split(self):
        self.root.mkdir()
        (self.root / "file").write_bytes(b"x")

        rm_dir_parallel(self.root, workers=4)

        self.assertFalse(self.root.exists())

    def test_missing_path_is_not_an_error(self):
        rm_dir_parallel(self.root, workers=4)

    def test_does_not_follow_symlinks_out_of_the_tree(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep")
        self.build_tree(groups=3, entries=3)
        (self.root / "model" / "0" / "link").symlink_to(outside, target_is_directory=True)

        rm_dir_parallel(self.root, workers=2)

        self.assertFalse(self.root.exists())
        self.assertEqual((outside / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
