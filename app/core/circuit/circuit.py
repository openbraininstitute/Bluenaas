import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

from entitysdk.client import Client
from entitysdk.models import Circuit as EntitycoreCircuit
from entitysdk.models import MEModel as EntitycoreMEModel
from entitysdk.models.entity import Entity
from entitysdk.staging import stage_circuit, stage_sonata_from_memodel
from filelock import FileLock
from loguru import logger

from app.constants import (
    CIRCUIT_CONFIG_NAME,
    CIRCUIT_MEMODEL_MOD_DIR,
    CIRCUIT_MOD_DIR,
    READY_MARKER_FILE_NAME,
)
from app.core.exceptions import CircuitInitError
from app.domains.circuit.circuit import CircuitOrigin
from app.infrastructure.storage import get_circuit_location


def create_circuit(
    circuit_id: UUID,
    *,
    client: Client,
):
    model_entity = client.get_entity(entity_id=circuit_id, entity_type=Entity)

    if model_entity.type == CircuitOrigin.CIRCUIT.value:
        return Circuit(circuit_id, client=client)
    elif model_entity.type == CircuitOrigin.MEMODEL.value:
        return MEModelCircuit(circuit_id, client=client)
    else:
        raise ValueError(f"Unknown circuit type: {model_entity.type}")


class CircuitBase(ABC):
    circuit_id: UUID
    initialized: bool = False
    path: Path

    def __init__(self, circuit_id: UUID, *, client: Client):
        self.circuit_id = circuit_id
        self.path = get_circuit_location(self.circuit_id)

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

        lock = FileLock(self.path / "dir.lock")

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
