from datetime import UTC, datetime
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from loguru import logger

from app.domains.job import JobStatus
from app.config.settings import settings
from app.core.job_stream import JobStream
from app.core.circuit.circuit import Circuit
from app.core.circuit.simulation import Simulation
from app.infrastructure.rq import get_job_stream_key
from entitysdk.models import SimulationExecution


def run_circuit_simulation(
    *,
    circuit_id: str,
    simulation_id: str,
    execution_id: str,
    access_token: str,
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

    logger.info(f"Initializing circuit {circuit_id}")
    job_stream.send_status(JobStatus.running, "circuit_init")
    circuit.init()

    simulation = Simulation(
        circuit_id=circuit_id,
        simulation_id=simulation_id,
        client=client,
        execution_id=execution_id,
    )

    job_stream.send_status(JobStatus.running, "simultaion_init")
    simulation.init()

    job_stream.send_status(JobStatus.running, "simulation_exec")
    # TODO: Add logic to pick more cpus when needed
    simulation_output = simulation.run(num_cores=1)

    job_stream.send_status(JobStatus.running, "results_upload")
    simulation_result_entity = simulation_output.upload()

    res = client.update_entity(
        entity_id=UUID(execution_id),
        entity_type=SimulationExecution,
        attrs_or_entity={
            "generated_ids": [simulation_result_entity.id],
            "end_time": datetime.now(UTC),
            "status": "done",
        },
    )

    logger.info(res)

    job_stream.send_status(JobStatus.done)
    job_stream.close()
