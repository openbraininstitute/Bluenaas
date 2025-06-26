from uuid import UUID, uuid4
from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from rq import Queue
from datetime import UTC, datetime

from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch
from app.config.settings import settings
from entitysdk.client import Client
from entitysdk.models import SimulationExecution, Simulation
from entitysdk.types import SimulationExecutionStatus


class SimulationRequest(BaseModel):
    simulation_id: str
    project_context: ProjectContext


async def run_circuit_simulation(
    *,
    request: Request,
    job_queue: Queue,
    simulation_request: SimulationRequest,
    access_token: str,
):
    # TODO: Get rid of circuit_id param, fetch it from entitycore.

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=simulation_request.project_context,
        token_manager=access_token,
    )

    simulation = client.get_entity(
        UUID(simulation_request.simulation_id),
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
        stream_queue_position=True,
        job_kwargs={
            "circuit_id": simulation.entity_id,
            "simulation_id": simulation_request.simulation_id,
            "execution_id": simulation_execution.id,
            "access_token": access_token,
            "project_context": simulation_request.project_context,
        },
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
