import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

from entitysdk.client import Client
from entitysdk.models import Circuit as EntitycoreCircuit
from entitysdk.models import Entity
from entitysdk.models import IonChannelModel as EntitycoreIonChannelModel
from entitysdk.models import MEModel as EntitycoreMEModel
from entitysdk.models import Simulation as EntitycoreSimulation
from entitysdk.staging import stage_circuit, stage_sonata_from_memodel
from entitysdk.staging.ion_channel_model import (
    stage_sonata_from_config as stage_sonata_from_ionchannelmodel,
)
from entitysdk.types import AssetLabel
from filelock import FileLock
from loguru import logger
from obi_one import IonChannelModelSimulationSingleConfig
from obi_one.scientific.blocks.ion_channel_model import (
    IonChannelModelWithConductance,
    IonChannelModelWithMaxPermeability,
)

from app.constants import (
    CIRCUIT_CONFIG_NAME,
    CIRCUIT_MEMODEL_MOD_DIR,
    CIRCUIT_MOD_DIR,
    DIR_LOCK_FILE_NAME,
    READY_MARKER_FILE_NAME,
)
from app.core.exceptions import CircuitInitError
from app.domains.circuit.circuit import CircuitOrigin
from app.infrastructure.storage import get_circuit_location, rm_dir


class CircuitBase(ABC):
    circuit_id: UUID
    initialized: bool = False
    path: Path

    def __init__(self, circuit_id: UUID, *, client: Client, cache_entry_id: UUID | None = None):
        self.circuit_id = circuit_id
        self.path = get_circuit_location(cache_entry_id or self.circuit_id)

        self.client = client

        self._fetch_metadata()

    @abstractmethod
    def _fetch_metadata(self):
        """Fetch the circuit metadata from entitycore"""
        pass

    @abstractmethod
    def _fetch_assets(self):
        """Fetch the circuit files from entitycore and write to the disk storage"""
        pass

    def _compile_mod_files(self):
        """Compile MOD files"""
        mech_path = self.path / CIRCUIT_MOD_DIR
        if not mech_path.is_dir():
            err_msg = f"'{CIRCUIT_MOD_DIR}' folder not found under {self.path}"
            raise FileNotFoundError(err_msg)

        # TODO: add additional arg to ensure custom mod files compilation
        # Check with Darshan
        cmd = ["nrnivmodl", "-incflags", "-DDISABLE_REPORTINGLIB", CIRCUIT_MOD_DIR]
        compilation_output = subprocess.check_output(cmd, cwd=self.path)
        logger.debug(compilation_output.decode())

    def init(self):
        """Fetch circuit assets and compile MOD files"""
        if self.initialized:
            logger.warning("Circuit already initialized")
            return

        ready_marker = self.path / READY_MARKER_FILE_NAME

        if ready_marker.exists():
            logger.debug("Found existing circuit in the storage")
            self.initialized = True
            return

        lock = FileLock(self.path / DIR_LOCK_FILE_NAME)

        try:
            with lock.acquire(timeout=2 * 60):
                # Re-check if the circuit is already initialized.
                # Another worker might have initialized the circuit
                # while the current one was waiting for the lock.
                if ready_marker.exists():
                    logger.debug("Found existing circuit in the storage")
                    self.initialized = True
                    return

                self._fetch_assets()
                self._compile_mod_files()
                ready_marker.touch()
        except Exception:
            raise CircuitInitError()

    def cleanup(self) -> None:
        """Remove circuit files from storage. No-op by default."""
        pass

    def is_fetched(self) -> bool:
        """Check if the circuit is in the storage"""
        ready_marker = self.path / READY_MARKER_FILE_NAME
        return ready_marker.exists()


class Circuit(CircuitBase):
    metadata: EntitycoreCircuit

    def _fetch_metadata(self):
        """Fetch the circuit metadata from entitycore"""
        self.metadata = self.client.get_entity(self.circuit_id, entity_type=EntitycoreCircuit)

    def _fetch_assets(self):
        """Fetch the circuit files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None
        stage_circuit(self.client, model=self.metadata, output_dir=self.path, max_concurrent=8)

        # --------- TODO remove this ---------------------------------------------------------------
        config_file = self.path / CIRCUIT_CONFIG_NAME
        with open(config_file, "r") as f:
            config_data = json.load(f)

        config_data["networks"]["edges"] = [
            edge
            for edge in config_data["networks"]["edges"]
            if not (
                "hippocampus" in edge["edges_file"].lower()
                and "projections" in edge["edges_file"].lower()
            )
        ]

        with open(config_file, "w") as f:
            json.dump(config_data, f, indent=2)
        # ------------------------------------------------------------------------------------------

        logger.info(f"Circuit {self.circuit_id} fetched")


class MEModelCircuit(CircuitBase):
    metadata: EntitycoreMEModel

    def _fetch_metadata(self):
        """Fetch the ME-model metadata from entitycore"""
        self.metadata = self.client.get_entity(self.circuit_id, entity_type=EntitycoreMEModel)

    def _fetch_assets(self):
        """Fetch the ME-model files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None
        stage_sonata_from_memodel(self.client, memodel=self.metadata, output_dir=self.path)
        mod_path = self.path / CIRCUIT_MEMODEL_MOD_DIR
        mod_path.rename(self.path / CIRCUIT_MOD_DIR)


class IonChannelModelCircuit(CircuitBase):
    metadata: EntitycoreIonChannelModel
    simulation_id: UUID
    simulation: EntitycoreSimulation

    def __init__(self, circuit_id: UUID, *, client: Client, simulation_id: UUID):
        self.simulation_id = simulation_id
        super().__init__(circuit_id, client=client, cache_entry_id=simulation_id)

    def _fetch_metadata(self):
        """Fetch the Ion Channel Model metadata from entitycore"""
        self.metadata = self.client.get_entity(
            self.circuit_id, entity_type=EntitycoreIonChannelModel
        )

        self.simulation = self.client.get_entity(
            self.simulation_id, entity_type=EntitycoreSimulation
        )

    def _fetch_assets(self):
        """Fetch the Ion Channel Model files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None

        task_config_asset = next(
            (
                asset
                for asset in self.simulation.assets
                if asset.label == AssetLabel.simulation_generation_config
            ),
            None,
        )
        assert task_config_asset is not None, "Task config asset not found in the simulation assets"

        task_config_content = self.client.download_content(
            entity_id=self.simulation_id,
            entity_type=EntitycoreSimulation,
            asset_id=task_config_asset.id,
        )

        task_config = json.loads(task_config_content)

        config = IonChannelModelSimulationSingleConfig.model_validate(task_config)

        # TODO: this logic will be eventually moved to obi-one, clean up when that happens.
        ion_channel_model_data = {}
        for key, ic_data in config.ion_channel_models.items():
            conductance = {}
            if isinstance(
                ic_data, IonChannelModelWithConductance
            ) and ic_data.ion_channel_model.has_conductance(db_client=self.client):
                conductance = {
                    ic_data.ion_channel_model.get_conductance_name(
                        db_client=self.client
                    ): ic_data.conductance
                }
            elif isinstance(
                ic_data, IonChannelModelWithMaxPermeability
            ) and ic_data.ion_channel_model.has_max_permeability(db_client=self.client):
                conductance = {
                    ic_data.ion_channel_model.get_max_permeability_name(
                        db_client=self.client
                    ): ic_data.max_permeability
                }
            ion_channel_model_data[key] = {
                "id": ic_data.ion_channel_model.id_str,
            }
            ion_channel_model_data[key].update(conductance)

        stage_sonata_from_ionchannelmodel(
            self.client,
            ion_channel_model_data=ion_channel_model_data,
            output_dir=self.path,
            radius=12.6157 / 2.0,
        )

        # Move mod files to the expected location for compilation
        mod_path = self.path / CIRCUIT_MEMODEL_MOD_DIR
        mod_path.rename(self.path / CIRCUIT_MOD_DIR)

    def cleanup(self) -> None:
        """
        Circuits staged from ion channel models are simulation scoped,
        so have to be removed from the storage after their use.
        """
        self.initialized = False
        rm_dir(self.path)


_CIRCUIT_REGISTRY: dict[CircuitOrigin, type[CircuitBase]] = {
    CircuitOrigin.CIRCUIT: Circuit,
    CircuitOrigin.MEMODEL: MEModelCircuit,
    CircuitOrigin.ION_CHANNEL_MODEL: IonChannelModelCircuit,
}


def create_circuit(
    circuit_id: UUID,
    *,
    client: Client,
    simulation_id: UUID | None = None,
) -> CircuitBase:
    model_entity = client.get_entity(entity_id=circuit_id, entity_type=Entity)

    cls = _CIRCUIT_REGISTRY.get(CircuitOrigin(model_entity.type))

    if cls is None:
        raise ValueError(f"Unknown circuit type: {model_entity.type}")

    if cls is IonChannelModelCircuit:
        assert simulation_id is not None, "simulation_id is required for IonChannelModelCircuit"
        return cls(circuit_id, client=client, simulation_id=simulation_id)

    return cls(circuit_id, client=client)
