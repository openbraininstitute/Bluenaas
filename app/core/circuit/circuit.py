import json
from pathlib import Path
import subprocess
from uuid import UUID
from entitysdk.client import Client
from entitysdk.staging import stage_circuit
from entitysdk.models.circuit import Circuit as EntitycoreCircuit
from filelock import FileLock
from loguru import logger

from app.constants import (
    CIRCUIT_MOD_DIR,
    CIRCUIT_CONFIG_NAME,
    READY_MARKER_FILE_NAME,
)
from app.core.exceptions import CircuitInitError
from app.infrastructure.storage import get_circuit_location


class Circuit:
    circuit_id: UUID
    initialized: bool = False
    metadata: EntitycoreCircuit
    path: Path

    def __init__(self, circuit_id: UUID, client: Client):
        self.circuit_id = circuit_id
        self.path = get_circuit_location(self.circuit_id)

        self.client = client

        self._fetch_metadata()

    def _fetch_metadata(self):
        """Fetch the circuit metadata from entitycore"""
        self.metadata = self.client.get_entity(
            self.circuit_id, entity_type=EntitycoreCircuit
        )

    def _fetch_assets(self):
        """Fetch the circuit files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None
        stage_circuit(
            self.client, model=self.metadata, output_dir=self.path, max_concurrent=8
        )

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

    def _compile_mod_files(self):
        """Compile MOD files"""
        mech_path = self.path / CIRCUIT_MOD_DIR
        if not mech_path.is_dir():
            err_msg = f"'{CIRCUIT_MOD_DIR}' folder not found under {self.path}"
            raise FileNotFoundError(err_msg)

        # TODO: add additional arg to ensure custom mod files compilation
        # Check with Darshan
        cmd = ["nrnivmodl", CIRCUIT_MOD_DIR]
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
                self._fetch_assets()
                self._compile_mod_files()
                ready_marker.touch()
        except Exception:
            raise CircuitInitError()

    def is_fetched(self) -> bool:
        """Check if the circuit is in the storage"""
        ready_marker = self.path / READY_MARKER_FILE_NAME
        return ready_marker.exists()
