from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from entitysdk.models import Simulation, SimulationExecution
from entitysdk.types import SimulationExecutionStatus
from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.config.settings import settings
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


async def run_circuit_simulation(
    simulation_id: UUID,
    *,
    request: Request,
    job_queue: Queue,
    project_context: ProjectContext,
    access_token: str,
) -> StreamingResponse:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    simulation = client.get_entity(
        simulation_id,
        entity_type=Simulation,
    )

    simulation_execution = client.register_entity(
        SimulationExecution(
            used=[simulation],
            start_time=datetime.now(UTC),
            status=SimulationExecutionStatus.pending,
        )
    )

    _job, stream = await dispatch(
        job_queue,
        JobFn.RUN_CIRCUIT_SIMULATION,
        job_id=str(simulation_execution.id),
        job_kwargs={
            "circuit_id": simulation.entity_id,
            "simulation_id": simulation_id,
            "execution_id": simulation_execution.id,
            "access_token": access_token,
            "project_context": project_context,
        },
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(
        http_stream, media_type="application/x-ndjson", status_code=HTTPStatus.ACCEPTED
    )
