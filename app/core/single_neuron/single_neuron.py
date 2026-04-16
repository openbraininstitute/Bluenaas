from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from os import chdir
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from entitysdk import Client
from entitysdk.downloaders.cell_morphology import download_morphology
from entitysdk.downloaders.emodel import download_hoc
from entitysdk.downloaders.ion_channel_model import download_ion_channel_mechanism
from entitysdk.downloaders.memodel import download_memodel
from entitysdk.exception import IteratorResultError
from entitysdk.models import CellMorphology, EModel, MEModel
from filelock import FileLock
from loguru import logger

from app.constants import (
    DIR_LOCK_FILE_NAME,
    READY_MARKER_FILE_NAME,
    SINGLE_NEURON_HOC_DIR,
    SINGLE_NEURON_MOD_DIR,
    SINGLE_NEURON_MORPHOLOGY_DIR,
)
from app.core.compilation_cache import compile_with_cache
from app.core.exceptions import SingleNeuronInitError
from app.infrastructure.storage import (
    copy_file_content,
    get_model_candidate_location,
    get_single_neuron_location,
    rm_dir,
)


class SingleNeuronBase(ABC):
    path: Path
    initialized: bool = False
    cell: Any

    def __init__(self, path: Path):
        self.path = path

    @abstractmethod
    def _fetch_assets(self):
        """Fetch model assets from external storage and write to disk."""

    @property
    @abstractmethod
    def holding_current(self) -> float: ...

    @property
    @abstractmethod
    def threshold_current(self) -> float: ...

    def _add_syn_mod_files(self):
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

    def _init_model_files(self):
        ready_marker = self.path / READY_MARKER_FILE_NAME

        if ready_marker.exists():
            logger.debug("Found existing single neuron model in the storage")
            return

        lock = FileLock(self.path / DIR_LOCK_FILE_NAME)

        with lock.acquire(timeout=2 * 60):
            if ready_marker.exists():
                logger.debug("Found existing single neuron model in the storage")
                return

            self._fetch_assets()
            self._add_syn_mod_files()
            compile_with_cache(self.path, SINGLE_NEURON_MOD_DIR)
            ready_marker.touch()

    def _init_bcl_cell(self):
        chdir(self.path)

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

        logger.debug("BCL Cell initialized")

    def init_files(self):
        """Fetch model assets and compile MOD files (no Cell creation)."""
        try:
            self._init_model_files()
        except Exception:
            raise SingleNeuronInitError()

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

    def cleanup(self) -> None:
        """Remove model files from storage. No-op by default."""
        pass

    def is_fetched(self) -> bool:
        """Check if the model files are in the storage"""
        ready_marker = self.path / READY_MARKER_FILE_NAME
        return ready_marker.exists()


class SingleNeuron(SingleNeuronBase):
    model_id: UUID
    metadata: MEModel

    def __init__(self, model_id: UUID, client: Client):
        self.model_id = model_id
        self.client = client

        path = get_single_neuron_location(self.model_id)
        super().__init__(path)

        self._fetch_metadata()

    def _fetch_metadata(self):
        """Fetch the circuit metadata from entitycore"""
        self.metadata = self.client.get_entity(self.model_id, entity_type=MEModel)

    def _fetch_assets(self):
        """Fetch the circuit files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None

        logger.debug(f"Fetching single neuron model {self.model_id}")
        download_memodel(self.client, memodel=self.metadata, output_dir=str(self.path))

    @property
    def holding_current(self) -> float:
        calibration_result = self.metadata.calibration_result
        return calibration_result.holding_current if calibration_result else 0

    @property
    def threshold_current(self) -> float:
        calibration_result = self.metadata.calibration_result
        return calibration_result.threshold_current if calibration_result else 0.1


class SingleNeuronCandidate(SingleNeuronBase):
    """A single neuron assembled from separate morphology + emodel (no MEModel entity)."""

    morphology_id: UUID
    emodel_id: UUID

    def __init__(self, morphology_id: UUID, emodel_id: UUID, client: Client):
        self.morphology_id = morphology_id
        self.emodel_id = emodel_id
        self.client = client

        path = get_model_candidate_location(morphology_id, emodel_id)
        super().__init__(path)

        self._morphology = client.get_entity(morphology_id, entity_type=CellMorphology)
        self._emodel = cast(
            EModel,
            client.get_entity(emodel_id, entity_type=EModel),
        )

    def _fetch_assets(self):
        """Download HOC, morphology, and MOD files in parallel from separate entities."""
        hoc_dir = self.path / SINGLE_NEURON_HOC_DIR
        morphology_dir = self.path / SINGLE_NEURON_MORPHOLOGY_DIR
        mechanisms_dir = self.path / SINGLE_NEURON_MOD_DIR
        mechanisms_dir.mkdir(parents=True, exist_ok=True)

        def fetch_hoc():
            download_hoc(self.client, self._emodel, hoc_dir)

        def fetch_morphology():
            try:
                download_morphology(self.client, self._morphology, morphology_dir, "asc")
            except IteratorResultError:
                download_morphology(self.client, self._morphology, morphology_dir, "swc")

        def fetch_mechanism(ic):
            download_ion_channel_mechanism(self.client, ic, mechanisms_dir)

        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(fetch_hoc),
                executor.submit(fetch_morphology),
            ]
            for ic in self._emodel.ion_channel_models or []:
                futures.append(executor.submit(fetch_mechanism, ic))

            for future in as_completed(futures):
                future.result()  # Raises if any download failed

    def cleanup(self) -> None:
        """Remove temporary model candidate files from storage."""
        self.initialized = False
        rm_dir(self.path)

    @property
    def holding_current(self) -> float:
        return 0

    @property
    def threshold_current(self) -> float:
        return 0.1
