import json
import subprocess
from os.path import relpath
from pathlib import Path
from uuid import UUID, uuid4

from entitysdk.client import Client
from entitysdk.models.simulation import Simulation as EntitycoreSimulation
from entitysdk.staging import stage_simulation
from filelock import FileLock
from loguru import logger

from app.constants import (
    DEFAULT_CIRCUIT_CONFIG_NAME,
    DEFAULT_CIRCUIT_SIMULATION_CONFIG_NAME,
    DEFAULT_LIBNRNMECH_PATH,
)
from app.core.circuit.circuit import Circuit
from app.core.circuit.simulation_output import SimulationOutput
from app.infrastructure.storage import (
    get_circuit_simulation_location,
    get_circuit_simulation_output_location,
)


class Simulation:
    circuit: Circuit
    simulation_output: SimulationOutput | None = None
    initialized: bool = False
    metadata: EntitycoreSimulation
    simulation_id: str
    path: Path
    execution_id: str

    def __init__(
        self,
        circuit_id: str,
        simulation_id: str,
        client: Client,
        execution_id: str = str(uuid4()),
    ):
        self.simulation_id = simulation_id
        self.execution_id = execution_id
        self.client = client

        self.path = get_circuit_simulation_location(self.execution_id)

        self.circuit = Circuit(circuit_id, client)

        self._fetch_metadata()

    def _fetch_metadata(self):
        """Fetch the simulation (config) metadata from entitycore"""
        self.metadata = self.client.get_entity(
            UUID(self.simulation_id), entity_type=EntitycoreSimulation
        )

    def _fetch_assets(self):
        """Fetch the simulation (config) files from entitycore and write to the disk storage"""
        assert self.metadata.id
        assert self.circuit.path

        self.circuit.init()

        abs_output_path = get_circuit_simulation_output_location(self.execution_id)
        rel_output_path = Path(relpath(abs_output_path, self.path))

        stage_simulation(
            self.client,
            model=self.metadata,
            output_dir=self.path,
            circuit_config_path=self.circuit.path / DEFAULT_CIRCUIT_CONFIG_NAME,
            override_results_dir=rel_output_path,
        )

        # TODO: Remove this after target_simulator is fixed in obi-one API
        config_file = self.path / DEFAULT_CIRCUIT_SIMULATION_CONFIG_NAME
        with open(config_file, "r") as f:
            config_data = json.load(f)
        config_data["target_simulator"] = "NEURON"
        with open(config_file, "w") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"Simulation {self.simulation_id} fetched")

    def init(self):
        """Fetch simulation (config) assets and compile MOD files"""
        if self.initialized:
            logger.warning("Simulation config already initialized")
            return

        done_file = self.path / "done"

        if done_file.exists():
            logger.debug("Found existing simulation config in the storage")
            self.initialized = True
            return

        lock = FileLock(self.path / "dir.lock")
        with lock.acquire(timeout=2 * 60):
            self._fetch_assets()
            done_file.touch()

    def run(self, num_cores: int = 4) -> SimulationOutput:
        # Run the simulation via MPI entrypoint

        assert self.metadata.id

        # This ensures the output folder exists
        self.simulation_output = SimulationOutput(
            simulation_id=str(self.metadata.id),
            execution_id=self.execution_id,
            client=self.client,
        )

        # TODO: Check exit status code
        run_cmd = [
            "mpiexec",
            "-n",
            str(num_cores),
            "python",
            "/app/app/core/circuit/simulation-mpi-entrypoint.py",
            "--config",
            f"{self.path}/{DEFAULT_CIRCUIT_SIMULATION_CONFIG_NAME}",
            "--execution_id",
            self.execution_id,
            "--libnrnmech_path",
            # TODO: Consider adding support for other platforms/architectures
            f"{self.circuit.path}/{DEFAULT_LIBNRNMECH_PATH}",
            "--save-nwb",
        ]
        subprocess.run(run_cmd, cwd=self.circuit.path)

        return self.simulation_output
