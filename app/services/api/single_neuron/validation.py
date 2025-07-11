from uuid import UUID, uuid4

from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


async def run_validation_service(
    model_id: UUID,
    *,
    request: Request,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
) -> StreamingResponse:
    execution_id = uuid4()

    _job, stream = await dispatch(
        job_queue,
        JobFn.RUN_SINGLE_NEURON_VALIDATION,
        job_id=str(execution_id),
        job_args=(model_id,),
        job_kwargs={
            "project_context": project_context,
            "access_token": auth.access_token,
            "execution_id": execution_id,
        },
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
