import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core import neuron_runtime
from app.core.exceptions import SingleNeuronAssetError


class TestNeuronRuntime(unittest.TestCase):
    """NEURON must get its mechanisms from the model directory, not from the cwd."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        neuron_runtime._loaded = None

    def tearDown(self):
        neuron_runtime._loaded = None
        shutil.rmtree(self.tmp_dir)

    def test_mechanisms_are_loaded_by_path(self):
        (self.tmp_dir / "x86_64").mkdir()

        with mock.patch("neuron.load_mechanisms", return_value=True) as load_mechanisms:
            neuron_runtime.load(self.tmp_dir)

        load_mechanisms.assert_called_once_with(str(self.tmp_dir))

    def test_a_model_built_on_neuron_builtins_needs_no_mechanisms(self):
        with mock.patch("neuron.load_mechanisms") as load_mechanisms:
            neuron_runtime.load(self.tmp_dir)

        load_mechanisms.assert_not_called()

    def test_mechanisms_that_do_not_load_are_reported_as_an_asset_failure(self):
        (self.tmp_dir / "x86_64").mkdir()

        with mock.patch("neuron.load_mechanisms", return_value=False):
            with self.assertRaises(SingleNeuronAssetError) as ctx:
                neuron_runtime.load(self.tmp_dir)

        self.assertIn("x86_64", ctx.exception.message)

    def test_reloading_the_same_model_leaves_neuron_alone(self):
        (self.tmp_dir / "x86_64").mkdir()

        with mock.patch("neuron.load_mechanisms", return_value=True) as load_mechanisms:
            neuron_runtime.load(self.tmp_dir)
            neuron_runtime.load(self.tmp_dir)

        load_mechanisms.assert_called_once()

    def test_a_second_model_in_the_same_process_is_refused(self):
        other_dir = self.tmp_dir / "other"
        other_dir.mkdir()

        with mock.patch("neuron.load_mechanisms", return_value=True):
            neuron_runtime.load(self.tmp_dir)

            with self.assertRaises(RuntimeError):
                neuron_runtime.load(other_dir)


if __name__ == "__main__":
    unittest.main()
