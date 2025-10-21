from datetime import UTC, datetime
from typing import List
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from entitysdk.models import SimulationExecution
from loguru import logger

from app.config.settings import settings
from app.core.circuit.circuit import create_circuit
from app.core.circuit.simulation import Simulation
from app.core.job_stream import JobStream
from app.domains.circuit.circuit import CircuitOrigin
from app.domains.job import JobStatus
from app.infrastructure.rq import get_job_stream_key
from app.utils.rq_job import get_current_job_stream
from app.utils.simulation import get_num_mpi_procs


def run_circuit_simulation(
    simulation_id: UUID,
    *,
    access_token: str,
    circuit_id: UUID,
    circuit_origin: CircuitOrigin,
    execution_id: UUID,
    project_context: ProjectContext,
):
    job_stream = get_current_job_stream()

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    client.update_entity(
        entity_id=execution_id,
        entity_type=SimulationExecution,
        attrs_or_entity={
            "status": "running",
        },
    )

    circuit = create_circuit(circuit_id, client=client, circuit_origin=circuit_origin)

    simulation = Simulation(
        client=client,
        circuit_origin=circuit_origin,
        execution_id=execution_id,
        simulation_id=simulation_id,
    )

    status: JobStatus | None = None

    try:
        logger.info(f"Initializing circuit {circuit_id}")
        job_stream.send_status(JobStatus.running, "circuit_init")
        circuit.init()

        job_stream.send_status(JobStatus.running, "simulation_init")
        simulation.init()

        sim_params = simulation.get_simulation_params()
        num_mpi_procs = get_num_mpi_procs(sim_params.num_cells)

        job_stream.send_status(JobStatus.running, "simulation_exec")
        simulation.run(num_procs=num_mpi_procs)

        status = JobStatus.done
    except Exception as e:
        logger.exception(e)
        status = JobStatus.error
    finally:
        job_stream.send_status(JobStatus.running, "results_upload")
        simulation_result_entity = simulation.output.upload()

        client.update_entity(
            entity_id=execution_id,
            entity_type=SimulationExecution,
            attrs_or_entity={
                "generated_ids": [simulation_result_entity.id],
                "end_time": datetime.now(UTC),
                "status": status,
            },
        )

        job_stream.send_status(status or JobStatus.error)
        job_stream.close()

        simulation.cleanup()


def get_circuit_simulation_params(
    simulation_id: UUID,
    circuit_origin: CircuitOrigin,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    job_stream = JobStream(get_job_stream_key())

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    simulation = Simulation(simulation_id, circuit_origin=circuit_origin, client=client)

    try:
        simulation.init(init_circuit=False)

        sim_params = simulation.get_simulation_params()
        job_stream.send_data(sim_params)
    except Exception as e:
        logger.exception(e)
        job_stream.send_status(JobStatus.error, str(e))
    finally:
        job_stream.close()
        simulation.cleanup()


def get_batch_circuit_simulation_params_map(
    simulation_ids: List[UUID],
    circuit_origin: CircuitOrigin,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    job_stream = JobStream(get_job_stream_key())

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    try:
        sim_params_map = {
            simulation_id: Simulation(simulation_id, circuit_origin=circuit_origin, client=client)
            .init()
            .get_simulation_params()
            for simulation_id in simulation_ids
        }
        job_stream.send_data(sim_params_map)
    except Exception as e:
        logger.exception(e)
        job_stream.send_status(JobStatus.error, str(e))
    finally:
        job_stream.close()
