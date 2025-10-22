from http import HTTPStatus

from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from rq import Queue

from app.core.http_stream import x_ndjson_http_stream
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.rq_job import dispatch


async def run_ion_channel_build(
    config: dict,
    *,
    request: Request,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
    stream: bool = False,
):
    job, job_stream = await dispatch(
        job_queue,
        JobFn.RUN_ION_CHANNEL_BUILD,
        timeout=60 * 10,  # 10 minutes
        job_args=(config,),
        job_kwargs={
            "access_token": auth.access_token,
            "project_context": project_context,
        },
    )

    if stream is True:
        http_stream = x_ndjson_http_stream(request, job_stream)
        return StreamingResponse(
            http_stream, media_type="application/x-ndjson", status_code=HTTPStatus.ACCEPTED
        )
    else:
        return JSONResponse({"id": job.id}, status_code=HTTPStatus.ACCEPTED)
