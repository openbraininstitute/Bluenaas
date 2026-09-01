import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.exceptions import SingleNeuronAssetError, SingleNeuronInitError
from app.core.single_neuron.single_neuron import SingleNeuronBase


class _StubNeuron(SingleNeuronBase):
    """Exercises SingleNeuronBase.init() without any entitycore assets."""

    def __init__(self, path: Path, *, files_error=None, cell_body=None):
        super().__init__(path)
        self._files_error = files_error
        self._cell_body = cell_body

    def _fetch_assets(self):
        pass

    def _init_model_files(self):
        if self._files_error is not None:
            raise self._files_error

    def _init_bcl_cell(self):
        if self._cell_body is not None:
            self._cell_body()

    @property
    def holding_current(self) -> float:
        return 0

    @property
    def threshold_current(self) -> float:
        return 0.1


class TestSingleNeuronInit(unittest.TestCase):
    """The failure a user sees must carry NEURON's own wording, not a constant string."""

    @classmethod
    def setUpClass(cls):
        from neuron import h

        cls.h = h
        h("""
            begintemplate InitTestBoom
            proc init() {
                execerror("Less than three axon sections are present!", \
"This emodel can't be run with such a morphology!")
            }
            endtemplate InitTestBoom
        """)

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_hoc_error_surfaces_as_an_incompatibility_with_neuron_wording(self):
        neuron = _StubNeuron(self.tmp_dir, cell_body=lambda: self.h.InitTestBoom())

        with self.assertRaises(SingleNeuronInitError) as ctx:
            neuron.init()

        error = ctx.exception

        self.assertEqual(
            error.message,
            "Less than three axon sections are present! "
            "This emodel can't be run with such a morphology!",
        )
        self.assertIn("Less than three axon sections", error.details or "")
        # The original NEURON exception stays chained, so worker logs keep the traceback.
        self.assertIsInstance(error.__cause__, RuntimeError)

    def test_details_exclude_neurons_import_banner(self):
        neuron = _StubNeuron(self.tmp_dir, cell_body=lambda: self.h.InitTestBoom())

        with self.assertRaises(SingleNeuronInitError) as ctx:
            neuron.init()

        self.assertNotIn("DISPLAY", ctx.exception.details or "")

    def test_asset_failure_is_not_reported_as_an_incompatibility(self):
        neuron = _StubNeuron(self.tmp_dir, files_error=TimeoutError("download timed out"))

        with self.assertRaises(SingleNeuronAssetError) as ctx:
            neuron.init()

        self.assertIn("download timed out", ctx.exception.message)

    def test_compiler_transcript_is_kept_on_a_compilation_failure(self):
        import subprocess

        failure = subprocess.CalledProcessError(1, "nrnivmodl", output="mod file syntax error")
        neuron = _StubNeuron(self.tmp_dir, files_error=failure)

        with self.assertRaises(SingleNeuronAssetError) as ctx:
            neuron.init()

        self.assertEqual(ctx.exception.details, "mod file syntax error")

    def test_successful_init_marks_the_model_initialized(self):
        neuron = _StubNeuron(self.tmp_dir)

        neuron.init()

        self.assertTrue(neuron.initialized)


if __name__ == "__main__":
    unittest.main()
