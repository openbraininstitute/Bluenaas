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
from app.core.exceptions import SingleNeuronAssetError, SingleNeuronInitError
from app.domains.neuron_model import CompatibilityCheckResponse, CompatibilityStatus


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")


@patch("app.core.single_neuron.compatibility.get_compatibility_result_location")
@patch("app.core.single_neuron.compatibility.SingleNeuronCandidate")
class TestCompatibilityChecker(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.candidate_path = Path(self.tmp_dir) / "candidate"
        self.candidate_path.mkdir()
        self.result_path = Path(self.tmp_dir) / "result"
        self.result_path.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def _checker(self, MockCandidate, mock_result_loc, *, init_error=None):
        mock_result_loc.return_value = self.result_path
        mock_candidate = MockCandidate.return_value
        mock_candidate.path = self.candidate_path
        mock_candidate.init.side_effect = init_error

        checker = CompatibilityChecker(MORPH_ID, EMODEL_ID, client=MagicMock())
        return checker, mock_candidate

    @property
    def _result_file(self) -> Path:
        return self.result_path / RESULT_FILE_NAME

    def test_cache_hit_returns_cached_result(self, MockCandidate, mock_result_loc):
        checker, mock_candidate = self._checker(MockCandidate, mock_result_loc)

        cached_data = CompatibilityCheckResponse(
            status=CompatibilityStatus.compatible,
            morphology_id=MORPH_ID,
            emodel_id=EMODEL_ID,
        )
        self._result_file.write_text(cached_data.model_dump_json())

        result = checker.run()

        self.assertIs(result.status, CompatibilityStatus.compatible)
        self.assertEqual(result.morphology_id, MORPH_ID)
        mock_candidate.init.assert_not_called()
        mock_candidate.cleanup.assert_not_called()

    def test_unreadable_cache_is_treated_as_a_miss(self, MockCandidate, mock_result_loc):
        checker, mock_candidate = self._checker(MockCandidate, mock_result_loc)
        self._result_file.write_text("{ not json at all")

        result = checker.run()

        self.assertIs(result.status, CompatibilityStatus.compatible)
        mock_candidate.init.assert_called_once()

    def test_successful_check(self, MockCandidate, mock_result_loc):
        checker, mock_candidate = self._checker(MockCandidate, mock_result_loc)

        result = checker.run()

        self.assertIs(result.status, CompatibilityStatus.compatible)
        self.assertTrue(result.compatible)
        self.assertIsNone(result.error)
        mock_candidate.init.assert_called_once()
        mock_candidate.cleanup.assert_called_once()

        self.assertTrue(json.loads(self._result_file.read_text())["compatible"])

    def test_init_error_reports_incompatible_with_details(self, MockCandidate, mock_result_loc):
        checker, mock_candidate = self._checker(
            MockCandidate,
            mock_result_loc,
            init_error=SingleNeuronInitError(
                "Less than three axon sections are present!",
                details="NEURON: Less than three axon sections are present!\n cADpyr[0].init()",
            ),
        )

        result = checker.run()

        self.assertIs(result.status, CompatibilityStatus.incompatible)
        self.assertFalse(result.compatible)
        self.assertEqual(result.error, "Less than three axon sections are present!")
        self.assertIn("cADpyr[0].init()", result.details or "")
        mock_candidate.cleanup.assert_called_once()

        self.assertFalse(json.loads(self._result_file.read_text())["compatible"])

    def test_asset_error_reports_check_failed_and_is_not_cached(
        self, MockCandidate, mock_result_loc
    ):
        checker, mock_candidate = self._checker(
            MockCandidate,
            mock_result_loc,
            init_error=SingleNeuronAssetError("download timed out"),
        )

        result = checker.run()

        self.assertIs(result.status, CompatibilityStatus.check_failed)
        self.assertFalse(result.compatible)
        self.assertEqual(result.error, "download timed out")
        mock_candidate.cleanup.assert_called_once()

        # Caching this would make a transient failure permanent for the pair.
        self.assertFalse(self._result_file.exists())

    def test_unexpected_error_reports_check_failed(self, MockCandidate, mock_result_loc):
        checker, mock_candidate = self._checker(
            MockCandidate, mock_result_loc, init_error=RuntimeError("NEURON crashed")
        )

        result = checker.run()

        self.assertIs(result.status, CompatibilityStatus.check_failed)
        self.assertFalse(self._result_file.exists())
        mock_candidate.cleanup.assert_called_once()

    def test_container_paths_are_scrubbed_from_details(self, MockCandidate, mock_result_loc):
        checker, _ = self._checker(
            MockCandidate,
            mock_result_loc,
            init_error=SingleNeuronInitError(
                "boom",
                details="NEURON: Couldn't find: /app/storage/single-neuron/ab/hoc/cell.hoc",
            ),
        )

        result = checker.run()

        self.assertNotIn("/app/storage", result.details or "")
        self.assertIn("cell.hoc", result.details or "")


if __name__ == "__main__":
    unittest.main()
