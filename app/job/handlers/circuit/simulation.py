from datetime import UTC, datetime
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from entitysdk.models import SimulationExecution
from entitysdk.types import SimulationExecutionStatus
from loguru import logger

from app.config.settings import settings
from app.core.circuit.circuit import Circuit
from app.core.circuit.simulation import Simulation
from app.core.job_stream import JobStream
from app.domains.job import JobStatus
from app.infrastructure.rq import get_job_stream_key
from app.utils.simulation import get_num_mpi_procs


def run_circuit_simulation(
    *,
    access_token: str,
    circuit_id: str,
    execution_id: str,
    simulation_id: str,
    project_context: ProjectContext,
):
    job_stream = JobStream(get_job_stream_key())

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    client.update_entity(
        entity_id=UUID(execution_id),
        entity_type=SimulationExecution,
        attrs_or_entity={
            "status": "running",
        },
    )

    circuit = Circuit(circuit_id=circuit_id, client=client)

    simulation = Simulation(
        circuit_id=circuit_id,
        client=client,
        execution_id=execution_id,
        simulation_id=simulation_id,
    )

    status: SimulationExecutionStatus | None = None

    try:
        logger.info(f"Initializing circuit {circuit_id}")
        job_stream.send_status(JobStatus.running, "circuit_init")
        circuit.init()

        job_stream.send_status(JobStatus.running, "simultaion_init")
        simulation.init()

        num_cells = simulation.get_num_cells()
        num_mpi_procs = get_num_mpi_procs(num_cells)

        job_stream.send_status(JobStatus.running, "simulation_exec")
        simulation.run(num_procs=num_mpi_procs)

        status = SimulationExecutionStatus.done
    except Exception as e:
        logger.exception(e)
        status = SimulationExecutionStatus.error
        raise
    finally:
        job_stream.send_status(JobStatus.running, "results_upload")
        simulation_result_entity = simulation.output.upload()

        client.update_entity(
            entity_id=UUID(execution_id),
            entity_type=SimulationExecution,
            attrs_or_entity={
                "generated_ids": [simulation_result_entity.id],
                "end_time": datetime.now(UTC),
                "status": status,
            },
        )
