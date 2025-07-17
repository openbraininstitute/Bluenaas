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
    CIRCUIT_CONFIG_NAME,
    CIRCUIT_SIMULATION_CONFIG_NAME,
    LIBNRNMECH_PATH,
    READY_MARKER_FILE_NAME,
)
from app.core.circuit.circuit import Circuit
from app.core.circuit.simulation_output import SimulationOutput
from app.core.exceptions import CircuitSimulationError, CircuitSimulationInitError
from app.domains.circuit.simulation import SimulationParams
from app.infrastructure.storage import (
    get_circuit_simulation_location,
    get_circuit_simulation_output_location,
    rm_dir,
)


class Simulation:
    circuit: Circuit
    output: SimulationOutput
    initialized: bool = False
    metadata: EntitycoreSimulation
    simulation_id: UUID
    path: Path
    execution_id: UUID

    def __init__(
        self,
        circuit_id: UUID,
        simulation_id: UUID,
        client: Client,
        execution_id: UUID = uuid4(),
    ):
        self.simulation_id = simulation_id
        self.execution_id = execution_id
        self.client = client

        self.path = get_circuit_simulation_location(self.execution_id)

        self.circuit = Circuit(circuit_id, client=client)

        self._fetch_metadata()

        # So that we can upload generated results, including logs even if circuit init fails.
        self._init_output()

    def _fetch_metadata(self):
        """Fetch the simulation (config) metadata from entitycore"""
        self.metadata = self.client.get_entity(self.simulation_id, entity_type=EntitycoreSimulation)

    def _fetch_assets(self):
        """Fetch the simulation (config) files from entitycore and write to the disk storage"""
        assert self.metadata.id
        assert self.circuit.path

        abs_output_path = get_circuit_simulation_output_location(self.execution_id)
        rel_output_path = Path(relpath(abs_output_path, self.path))

        stage_simulation(
            self.client,
            model=self.metadata,
            output_dir=self.path,
            circuit_config_path=self.circuit.path / CIRCUIT_CONFIG_NAME,
            override_results_dir=rel_output_path,
        )

        # Empty reports dict causes an exception in bluecellulab
        # TODO: Remove config overwrite after the above is fixed.
        # TODO: Move spike_file location overwrite to staging functions in entitysdk.
        config_file = self.path / CIRCUIT_SIMULATION_CONFIG_NAME
        with open(config_file, "r") as f:
            config_data = json.load(f)

        if len(config_data["reports"].keys()) == 0:
            del config_data["reports"]

        for input_name, input_value in config_data.get("inputs", {}).items():
            if "spike_file" in input_value:
                spike_f_path = str(self.path / input_value["spike_file"])
                logger.info(f"Overwriting spike file location for {input_name} with {spike_f_path}")
                input_value["spike_file"] = spike_f_path

        with open(config_file, "w") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"Simulation {self.simulation_id} fetched")

    def _init_output(self):
        assert self.metadata.id

        self.output = SimulationOutput(
            simulation_id=self.metadata.id,
            execution_id=self.execution_id,
            client=self.client,
        )

    def _init_circuit(self):
        self.circuit.init()

    def _init_simulation(self):
        """Fetch simulation (config) assets and compile MOD files"""
        if self.initialized:
            logger.warning("Simulation config already initialized")
            return

        ready_marker = self.path / READY_MARKER_FILE_NAME

        if ready_marker.exists():
            logger.debug("Found existing simulation config in the storage")
            self.initialized = True
            return

        lock = FileLock(self.path / "dir.lock")
        with lock.acquire(timeout=2 * 60):
            self._fetch_assets()
            ready_marker.touch()

    def get_simulation_params(self) -> SimulationParams:
        config_file = self.path / CIRCUIT_SIMULATION_CONFIG_NAME
        with open(config_file, "r") as f:
            config_data = json.load(f)
            node_set_name = config_data.get("node_set", "All")
            node_sets_file = self.path / config_data["node_sets_file"]

            with open(node_sets_file) as f:
                node_set_data = json.load(f)

                if node_set_name not in node_set_data:
                    raise KeyError(f"Node set '{node_set_name}' not found in node sets file")

                num_cells = len(node_set_data[node_set_name]["node_id"])
                tstop = config_data["run"]["tstop"]

                return SimulationParams(num_cells=num_cells, tstop=tstop)

    def init(self, *, init_circuit: bool = True):
        if init_circuit:
            self._init_circuit()

        try:
            self._init_simulation()
        except Exception:
            raise CircuitSimulationInitError()

    def run(self, *, num_procs: int = 1) -> SimulationOutput:
        # Run the simulation via MPI entrypoint

        # TODO: Check exit status code
        run_cmd = [
            "mpiexec",
            "-n",
            str(num_procs),
            "python",
            "/app/app/core/circuit/simulation-mpi-entrypoint.py",
            "--config",
            f"{self.path}/{CIRCUIT_SIMULATION_CONFIG_NAME}",
            "--execution_id",
            str(self.execution_id),
            "--libnrnmech_path",
            # TODO: Consider adding support for other platforms/architectures
            f"{self.circuit.path}/{LIBNRNMECH_PATH}",
            "--save-nwb",
        ]
        try:
            subprocess.run(run_cmd, cwd=self.circuit.path, check=True)
        except Exception:
            raise CircuitSimulationError()

        return self.output

    def cleanup(self):
        self.output.cleanup()

        # TODO: Make instance re-initializable
        self.initialized = False
        rm_dir(self.path)
