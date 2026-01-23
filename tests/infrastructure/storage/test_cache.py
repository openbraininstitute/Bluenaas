import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.infrastructure.storage import (
    clear_circuit_cache,
    clear_ion_channel_cache,
    clear_mesh_cache,
    clear_single_neuron_cache,
)


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


if __name__ == "__main__":
    unittest.main()
