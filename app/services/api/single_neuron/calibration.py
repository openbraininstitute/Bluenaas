from uuid import UUID, uuid4

from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


async def run_calibration_service(
    model_id: UUID,
    *,
    request: Request,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
) -> StreamingResponse:
    _job, stream = await dispatch(
        job_queue,
        JobFn.RUN_SINGLE_NEURON_CALIBRATION,
        job_args=(model_id,),
        job_kwargs={
            "project_context": project_context,
            "access_token": auth.access_token,
        },
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
