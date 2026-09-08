import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.exceptions import SingleNeuronAssetError, SingleNeuronInitError
from app.core.single_neuron.single_neuron import SingleNeuronBase
from tests.neuron_template import ERROR_MESSAGE, raise_hoc_error


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
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

        # init() loads the process-global mechanism table, and the stub ships no
        # mechanisms for it to load.
        patcher = mock.patch("app.core.neuron_runtime.load")
        self.mock_load = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_hoc_error_surfaces_as_an_incompatibility_with_neuron_wording(self):
        neuron = _StubNeuron(self.tmp_dir, cell_body=raise_hoc_error)

        with self.assertRaises(SingleNeuronInitError) as ctx:
            neuron.init()

        error = ctx.exception

        self.assertEqual(error.message, ERROR_MESSAGE)
        self.assertIn("Less than three axon sections", error.details or "")
        # The NEURON import banner must not end up in what a user reads.
        self.assertNotIn("DISPLAY", error.details or "")
        # Chaining keeps the NEURON traceback in the worker logs.
        self.assertIsInstance(error.__cause__, RuntimeError)

    def test_a_mechanism_failure_is_not_reported_as_an_incompatibility(self):
        self.mock_load.side_effect = SingleNeuronAssetError(
            "NEURON loaded no mechanisms from x86_64"
        )

        neuron = _StubNeuron(self.tmp_dir)

        with self.assertRaises(SingleNeuronAssetError):
            neuron.init()

    def test_a_failure_neuron_did_not_report_is_not_an_incompatibility(self):
        def empty_hoc_dir():
            next(iter([]))

        neuron = _StubNeuron(self.tmp_dir, cell_body=empty_hoc_dir)

        # An incompatibility is cached permanently, so only a failure NEURON reported
        # may be recorded as one.
        with self.assertRaises(StopIteration):
            neuron.init()

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
