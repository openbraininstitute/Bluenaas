from os import chdir
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from entitysdk import Client
from entitysdk.downloaders.memodel import download_memodel
from entitysdk.models import MEModel
from filelock import FileLock
from loguru import logger

from app.constants import (
    READY_MARKER_FILE_NAME,
    SINGLE_NEURON_HOC_DIR,
    SINGLE_NEURON_MOD_DIR,
    SINGLE_NEURON_MORPHOLOGY_DIR,
)
from app.core.exceptions import SingleNeuronInitError
from app.infrastructure.storage import copy_file_content, get_single_neuron_location


class SingleNeuron:
    model_id: UUID
    initialized: bool = False
    metadata: MEModel
    path: Path
    cell: Any

    def __init__(self, model_id: UUID, client: Client):
        self.model_id = model_id
        self.path = get_single_neuron_location(self.model_id)

        self.client = client

        self._fetch_metadata()

    def _fetch_metadata(self):
        """Fetch the circuit metadata from entitycore"""
        self.metadata = self.client.get_entity(self.model_id, entity_type=MEModel)

    def _fetch_assets(self):
        """Fetch the circuit files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None

        logger.debug(f"Fetching single neuron model {self.model_id}")
        download_memodel(self.client, memodel=self.metadata, output_dir=str(self.path))

    def _add_syn_mod_files(self):
        # TODO: Move this to a helper function.
        copy_file_content(
            Path("/app/app/config/VecStim.mod"),
            self.path / SINGLE_NEURON_MOD_DIR / "VecStim.mod",
        )
        copy_file_content(
            Path("/app/app/config/ProbGABAAB_EMS.mod"),
            self.path / SINGLE_NEURON_MOD_DIR / "ProbGABAAB_EMS.mod",
        )
        copy_file_content(
            Path("/app/app/config/ProbAMPANMDA_EMS.mod"),
            self.path / SINGLE_NEURON_MOD_DIR / "ProbAMPANMDA_EMS.mod",
        )

    def _compile_mod_files(self):
        """Compile MOD files"""
        mech_path = self.path / SINGLE_NEURON_MOD_DIR
        if not mech_path.is_dir():
            err_msg = f"'{SINGLE_NEURON_MOD_DIR}' folder not found under {self.path}"
            raise FileNotFoundError(err_msg)

        # TODO move to a separate module
        cmd = [
            "nrnivmodl",
            "-incflags",
            "-DDISABLE_REPORTINGLIB",
            SINGLE_NEURON_MOD_DIR,
        ]
        compilation_output = subprocess.check_output(
            cmd,
            cwd=self.path,
            text=True,
        )
        logger.debug(compilation_output)

    def _init_model_files(self):
        ready_marker = self.path / READY_MARKER_FILE_NAME

        if ready_marker.exists():
            logger.debug("Found existing single neuron model in the storage")
            return

        lock = FileLock(self.path / "dir.lock")

        with lock.acquire(timeout=2 * 60):
            # Re-check if the single neuron model is already initialized.
            # Another worker might have initialized the model
            # while the current one was waiting for the lock.
            if ready_marker.exists():
                logger.debug("Found existing single neuron model in the storage")
                return

            self._fetch_assets()
            self._add_syn_mod_files()
            self._compile_mod_files()
            ready_marker.touch()

    def _init_bcl_cell(self):
        # Consider using h.nrn_load_dll(libnrnmech_path) as with a circuit simulation
        chdir(self.path)

        # TODO Consider moving imports to the top
        # importing bluecellulab AFTER compiling the mechanisms to avoid segmentation fault
        from bluecellulab import Cell
        from bluecellulab.circuit.circuit_access import EmodelProperties

        emodel_properties = EmodelProperties(
            threshold_current=self.threshold_current,
            holding_current=self.holding_current,
            AIS_scaler=1.0,
        )

        hoc_dir_path = self.path / SINGLE_NEURON_HOC_DIR
        hoc_path = next(hoc_dir_path.iterdir())

        morphology_dir_path = self.path / SINGLE_NEURON_MORPHOLOGY_DIR
        morphology_path = next(morphology_dir_path.iterdir())

        self.cell = Cell(
            template_path=hoc_path,
            morphology_path=morphology_path,
            template_format="v6",
            emodel_properties=emodel_properties,
        )

        logger.debug(f"BCL Cell {self.model_id} initialized")

    def init(self):
        """Fetch model assets, compile MOD files and initialize BlueCelluLab Cell"""
        if self.initialized:
            logger.warning("Single neuron model already initialized")
            return

        try:
            self._init_model_files()
            self._init_bcl_cell()

            self.initialized = True

        except Exception:
            raise SingleNeuronInitError()

    @property
    def holding_current(self) -> float:
        calibration_result = self.metadata.calibration_result
        return calibration_result.holding_current if calibration_result else 0

    @property
    def threshold_current(self) -> float:
        calibration_result = self.metadata.calibration_result
        return calibration_result.threshold_current if calibration_result else 0.1

    def is_fetched(self) -> bool:
        """Check if the circuit is in the storage"""
        ready_marker = self.path / READY_MARKER_FILE_NAME
        return ready_marker.exists()
