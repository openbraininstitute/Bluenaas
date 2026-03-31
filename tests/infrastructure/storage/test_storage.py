import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.infrastructure.storage import (
    clear_circuit_cache,
    clear_ion_channel_cache,
    clear_mesh_cache,
    clear_single_neuron_cache,
    get_compatibility_result_location,
    get_model_candidate_location,
)


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")
MORPH_ID_ALT = UUID("33333333-3333-3333-3333-333333333333")


class TestClearCache(unittest.TestCase):
    @patch("app.infrastructure.storage.settings")
    @patch("app.infrastructure.storage.rm_dir")
    def test_clear_circuit_cache(self, mock_rm_dir, mock_settings):
        mock_settings.STORAGE_PATH = Path("/test/storage")
        clear_circuit_cache()
        mock_rm_dir.assert_called_once_with(Path("/test/storage/circuit"))

    @patch("app.infrastructure.storage.settings")
    @patch("app.infrastructure.storage.rm_dir")
    def test_clear_single_neuron_cache(self, mock_rm_dir, mock_settings):
        mock_settings.STORAGE_PATH = Path("/test/storage")
        clear_single_neuron_cache()
        mock_rm_dir.assert_called_once_with(Path("/test/storage/single-neuron"))

    @patch("app.infrastructure.storage.settings")
    @patch("app.infrastructure.storage.rm_dir")
    def test_clear_mesh_cache(self, mock_rm_dir, mock_settings):
        mock_settings.STORAGE_PATH = Path("/test/storage")
        clear_mesh_cache()
        mock_rm_dir.assert_called_once_with(Path("/test/storage/mesh"))

    @patch("app.infrastructure.storage.settings")
    @patch("app.infrastructure.storage.rm_dir")
    def test_clear_ion_channel_cache(self, mock_rm_dir, mock_settings):
        mock_settings.STORAGE_PATH = Path("/test/storage")
        clear_ion_channel_cache()
        mock_rm_dir.assert_called_once_with(Path("/test/storage/ion-channel"))


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


if __name__ == "__main__":
    unittest.main()
