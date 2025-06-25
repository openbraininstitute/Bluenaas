from pathlib import Path
import subprocess
from uuid import UUID
from entitysdk.client import Client
from entitysdk.staging import stage_circuit
from entitysdk.models.circuit import Circuit as EntitycoreCircuit
from filelock import FileLock
from loguru import logger

from app.constants import CIRCUIT_MOD_FOLDER
from app.infrastructure.storage import get_circuit_location


class Circuit:
    circuit_id: str
    initialized: bool = False
    metadata: EntitycoreCircuit
    path: Path

    def __init__(self, circuit_id: str, client: Client):
        self.circuit_id = circuit_id
        self.path = get_circuit_location(self.circuit_id)

        self.client = client

        self._fetch_metadata()

    def _fetch_metadata(self):
        """Fetch the circuit metadata from entitycore"""
        self.client.get_entity(UUID(self.circuit_id), entity_type=EntitycoreCircuit)

    def _fetch(self):
        """Fetch the circuit files from entitycore and write to the disk storage"""
        assert self.metadata.id is not None
        stage_circuit(self.client, model=self.metadata, output_dir=self.path)
        logger.info(f"Circuit {self.circuit_id} fetched")

    def _compile(self):
        """Compile MOD files"""
        mech_path = self.path / CIRCUIT_MOD_FOLDER
        if not mech_path.is_dir():
            err_msg = f"'{CIRCUIT_MOD_FOLDER}' folder not found under {self.path}"
            raise FileNotFoundError(err_msg)

        cmd = ["nrnivmodl", CIRCUIT_MOD_FOLDER]
        compilation_output = subprocess.check_output(cmd, cwd=self.path)
        logger.debug(compilation_output.decode())

    def init(self):
        """Fetch circuit assets and compile MOD files"""
        if self.initialized:
            logger.warning("Circuit already initialized")
            return

        done_file = self.path / "done"

        if done_file.exists():
            logger.debug("Found existing circuit in the storage")
            self.initialized = True
            return

        lock = FileLock(self.path / "dir.lock")
        with lock.acquire(timeout=2 * 60):
            self._fetch()
            self._compile()
            done_file.touch()

    def is_fetched(self) -> bool:
        """Check if the circuit is in the storage"""
        done_file = self.path / "done"
        return done_file.exists()
