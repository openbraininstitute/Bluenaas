import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core import neuron_runtime
from app.constants import LIBNRNMECH_PATH, MECHANISMS_DIR_NAME
from app.core.exceptions import SingleNeuronAssetError


class TestNeuronRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        neuron_runtime._loaded = None

    def tearDown(self):
        neuron_runtime._loaded = None
        shutil.rmtree(self.tmp_dir)

    def test_mechanisms_are_loaded_by_path(self):
        (self.tmp_dir / MECHANISMS_DIR_NAME).mkdir()

        with mock.patch("neuron.load_mechanisms", return_value=True) as load_mechanisms:
            neuron_runtime.load(self.tmp_dir)

        load_mechanisms.assert_called_once_with(str(self.tmp_dir))

    def test_a_model_built_on_neuron_builtins_needs_no_mechanisms(self):
        with mock.patch("neuron.load_mechanisms") as load_mechanisms:
            neuron_runtime.load(self.tmp_dir)

        load_mechanisms.assert_not_called()

    def test_mechanisms_that_do_not_load_are_reported_as_an_asset_failure(self):
        (self.tmp_dir / MECHANISMS_DIR_NAME).mkdir()

        with mock.patch("neuron.load_mechanisms", return_value=False):
            with self.assertRaises(SingleNeuronAssetError) as ctx:
                neuron_runtime.load(self.tmp_dir)

        self.assertIn(MECHANISMS_DIR_NAME, ctx.exception.message)

    def test_reloading_the_same_model_leaves_neuron_alone(self):
        (self.tmp_dir / MECHANISMS_DIR_NAME).mkdir()

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


class TestEnsureLibnrnmechLoaded(unittest.TestCase):
    """NEURON auto-loads ``./<arch>/libnrnmech.*`` from the working directory at hoc
    init; the circuit MPI entrypoint must not load that same library again."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.load_dll = mock.Mock()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_library_in_the_working_directory_is_not_loaded_again(self):
        circuit_dir = self.tmp_dir / "circuit"
        lib = circuit_dir / LIBNRNMECH_PATH
        lib.parent.mkdir(parents=True)
        lib.touch()

        with mock.patch.object(Path, "cwd", return_value=circuit_dir):
            neuron_runtime.ensure_libnrnmech_loaded(lib, self.load_dll)

        self.load_dll.assert_not_called()

    def test_library_outside_the_working_directory_is_loaded(self):
        lib = self.tmp_dir / "elsewhere" / Path(LIBNRNMECH_PATH).name
        lib.parent.mkdir(parents=True)
        lib.touch()

        neuron_runtime.ensure_libnrnmech_loaded(lib, self.load_dll)

        self.load_dll.assert_called_once_with(str(lib))

    def test_missing_library_loads_nothing(self):
        missing = self.tmp_dir / LIBNRNMECH_PATH

        neuron_runtime.ensure_libnrnmech_loaded(missing, self.load_dll)

        self.load_dll.assert_not_called()


if __name__ == "__main__":
    unittest.main()
