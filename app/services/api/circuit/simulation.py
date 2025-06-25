from uuid import uuid4
from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from rq import Queue

from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


class SimulationRequest(BaseModel):
    circuit_id: str
    simulation_id: str
    project_context: ProjectContext


async def run_circuit_simulation(
    *,
    request: Request,
    job_queue: Queue,
    simulation_request: SimulationRequest,
    access_token: str,
):
    # TODO: Create a simulation activity and use it's ID instead
    execution_id = uuid4()

    _job, stream = await dispatch(
        job_queue,
        JobFn.RUN_CIRCUIT_SIMULATION,
        stream_queue_position=True,
        job_kwargs={
            "circuit_id": simulation_request.circuit_id,
            "simulation_id": simulation_request.simulation_id,
            "execution_id": execution_id,
            "access_token": access_token,
            "project_context": simulation_request.project_context,
        },
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
