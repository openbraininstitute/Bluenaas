import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.single_neuron.compatibility import RESULT_FILE_NAME, CompatibilityChecker
from app.core.exceptions import SingleNeuronInitError
from app.domains.neuron_model import CompatibilityCheckResponse


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")


class TestCompatibilityChecker(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.candidate_path = Path(self.tmp_dir) / "candidate"
        self.candidate_path.mkdir()
        self.result_path = Path(self.tmp_dir) / "result"
        self.result_path.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    @patch("app.core.single_neuron.compatibility.get_compatibility_result_location")
    @patch("app.core.single_neuron.compatibility.SingleNeuronCandidate")
    def test_cache_hit_returns_cached_result(self, MockCandidate, mock_result_loc):
        mock_result_loc.return_value = self.result_path
        mock_candidate = MockCandidate.return_value
        mock_candidate.path = self.candidate_path

        cached_data = CompatibilityCheckResponse(
            compatible=True,
            morphology_id=MORPH_ID,
            emodel_id=EMODEL_ID,
            error=None,
        )
        (self.result_path / RESULT_FILE_NAME).write_text(cached_data.model_dump_json())

        client = MagicMock()
        checker = CompatibilityChecker(MORPH_ID, EMODEL_ID, client=client)
        result = checker.run()

        self.assertTrue(result.compatible)
        self.assertEqual(result.morphology_id, MORPH_ID)
        mock_candidate.init.assert_not_called()
        mock_candidate.cleanup.assert_not_called()

    @patch("app.core.single_neuron.compatibility.get_compatibility_result_location")
    @patch("app.core.single_neuron.compatibility.SingleNeuronCandidate")
    def test_successful_check(self, MockCandidate, mock_result_loc):
        mock_result_loc.return_value = self.result_path
        mock_candidate = MockCandidate.return_value
        mock_candidate.path = self.candidate_path

        client = MagicMock()
        checker = CompatibilityChecker(MORPH_ID, EMODEL_ID, client=client)
        result = checker.run()

        self.assertTrue(result.compatible)
        self.assertIsNone(result.error)
        mock_candidate.init.assert_called_once()
        mock_candidate.cleanup.assert_called_once()

        written = json.loads((self.result_path / RESULT_FILE_NAME).read_text())
        self.assertTrue(written["compatible"])

    @patch("app.core.single_neuron.compatibility.get_compatibility_result_location")
    @patch("app.core.single_neuron.compatibility.SingleNeuronCandidate")
    def test_failed_check(self, MockCandidate, mock_result_loc):
        mock_result_loc.return_value = self.result_path
        mock_candidate = MockCandidate.return_value
        mock_candidate.path = self.candidate_path
        mock_candidate.init.side_effect = SingleNeuronInitError()

        client = MagicMock()
        checker = CompatibilityChecker(MORPH_ID, EMODEL_ID, client=client)
        result = checker.run()

        self.assertFalse(result.compatible)
        self.assertIsNotNone(result.error)
        mock_candidate.cleanup.assert_called_once()

        written = json.loads((self.result_path / RESULT_FILE_NAME).read_text())
        self.assertFalse(written["compatible"])

    @patch("app.core.single_neuron.compatibility.get_compatibility_result_location")
    @patch("app.core.single_neuron.compatibility.SingleNeuronCandidate")
    def test_cleanup_called_on_init_exception(self, MockCandidate, mock_result_loc):
        mock_result_loc.return_value = self.result_path
        mock_candidate = MockCandidate.return_value
        mock_candidate.path = self.candidate_path
        mock_candidate.init.side_effect = RuntimeError("NEURON crashed")

        client = MagicMock()
        checker = CompatibilityChecker(MORPH_ID, EMODEL_ID, client=client)
        checker.run()

        mock_candidate.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
