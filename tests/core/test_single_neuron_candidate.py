import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.single_neuron.single_neuron import SingleNeuronCandidate


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")


class TestSingleNeuronCandidateCleanup(unittest.TestCase):
    @patch(
        "app.core.single_neuron.single_neuron.get_model_candidate_location",
    )
    def test_cleanup_removes_directory(self, mock_location):
        tmp_dir = tempfile.mkdtemp()
        mock_location.return_value = Path(tmp_dir)

        mock_client = MagicMock()
        candidate = SingleNeuronCandidate(MORPH_ID, EMODEL_ID, mock_client)
        candidate.initialized = True

        self.assertTrue(Path(tmp_dir).exists())

        candidate.cleanup()

        self.assertFalse(Path(tmp_dir).exists())
        self.assertFalse(candidate.initialized)

    @patch(
        "app.core.single_neuron.single_neuron.get_model_candidate_location",
    )
    def test_cleanup_noop_when_already_removed(self, mock_location):
        tmp_dir = tempfile.mkdtemp()
        mock_location.return_value = Path(tmp_dir)

        mock_client = MagicMock()
        candidate = SingleNeuronCandidate(MORPH_ID, EMODEL_ID, mock_client)

        shutil.rmtree(tmp_dir)
        # Should not raise
        candidate.cleanup()


class TestSingleNeuronCandidateFetchAssets(unittest.TestCase):
    @patch(
        "app.core.single_neuron.single_neuron.get_model_candidate_location",
    )
    @patch("app.core.single_neuron.single_neuron.download_ion_channel_mechanism")
    @patch("app.core.single_neuron.single_neuron.download_morphology")
    @patch("app.core.single_neuron.single_neuron.download_hoc")
    def test_fetch_assets_calls_all_downloaders(
        self, mock_hoc, mock_morph, mock_mechanism, mock_location
    ):
        tmp_dir = tempfile.mkdtemp()
        mock_location.return_value = Path(tmp_dir)

        mock_client = MagicMock()
        mock_emodel = MagicMock()
        ic1 = MagicMock()
        ic2 = MagicMock()
        mock_emodel.ion_channel_models = [ic1, ic2]
        mock_client.get_entity.side_effect = [MagicMock(), mock_emodel]

        candidate = SingleNeuronCandidate(MORPH_ID, EMODEL_ID, mock_client)
        candidate._fetch_assets()

        mock_hoc.assert_called_once()
        mock_morph.assert_called_once()
        self.assertEqual(mock_mechanism.call_count, 2)

        shutil.rmtree(tmp_dir)

    @patch(
        "app.core.single_neuron.single_neuron.get_model_candidate_location",
    )
    @patch("app.core.single_neuron.single_neuron.download_ion_channel_mechanism")
    @patch("app.core.single_neuron.single_neuron.download_morphology")
    @patch("app.core.single_neuron.single_neuron.download_hoc")
    def test_fetch_assets_morphology_fallback_to_swc(
        self, mock_hoc, mock_morph, mock_mechanism, mock_location
    ):
        from entitysdk.exception import IteratorResultError

        tmp_dir = tempfile.mkdtemp()
        mock_location.return_value = Path(tmp_dir)

        mock_client = MagicMock()
        mock_emodel = MagicMock()
        mock_emodel.ion_channel_models = []
        mock_client.get_entity.side_effect = [MagicMock(), mock_emodel]

        # First call (asc) fails, second call (swc) succeeds
        mock_morph.side_effect = [IteratorResultError("no asc"), None]

        candidate = SingleNeuronCandidate(MORPH_ID, EMODEL_ID, mock_client)
        candidate._fetch_assets()

        self.assertEqual(mock_morph.call_count, 2)
        first_call_format = mock_morph.call_args_list[0][0][3]
        second_call_format = mock_morph.call_args_list[1][0][3]
        self.assertEqual(first_call_format, "asc")
        self.assertEqual(second_call_format, "swc")

        shutil.rmtree(tmp_dir)

    @patch(
        "app.core.single_neuron.single_neuron.get_model_candidate_location",
    )
    @patch("app.core.single_neuron.single_neuron.download_ion_channel_mechanism")
    @patch("app.core.single_neuron.single_neuron.download_morphology")
    @patch("app.core.single_neuron.single_neuron.download_hoc")
    def test_fetch_assets_no_ion_channels(
        self, mock_hoc, mock_morph, mock_mechanism, mock_location
    ):
        tmp_dir = tempfile.mkdtemp()
        mock_location.return_value = Path(tmp_dir)

        mock_client = MagicMock()
        mock_emodel = MagicMock()
        mock_emodel.ion_channel_models = None
        mock_client.get_entity.side_effect = [MagicMock(), mock_emodel]

        candidate = SingleNeuronCandidate(MORPH_ID, EMODEL_ID, mock_client)
        candidate._fetch_assets()

        mock_hoc.assert_called_once()
        mock_morph.assert_called_once()
        mock_mechanism.assert_not_called()

        shutil.rmtree(tmp_dir)


class TestSingleNeuronCandidateProperties(unittest.TestCase):
    @patch(
        "app.core.single_neuron.single_neuron.get_model_candidate_location",
    )
    def test_default_currents(self, mock_location):
        mock_location.return_value = Path(tempfile.mkdtemp())

        mock_client = MagicMock()
        candidate = SingleNeuronCandidate(MORPH_ID, EMODEL_ID, mock_client)

        self.assertEqual(candidate.holding_current, 0)
        self.assertEqual(candidate.threshold_current, 0.1)

        shutil.rmtree(str(candidate.path))


if __name__ == "__main__":
    unittest.main()
