from http import HTTPStatus
from uuid import UUID

from entitysdk.common import ProjectContext
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.core.http_stream import x_ndjson_http_stream
from app.core.job import JobInfo
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.rq_job import dispatch, get_job_info, run_async


async def run_ion_channel_build(
    config: dict,
    *,
    request: Request,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
    stream: bool = False,
) -> JobInfo | StreamingResponse:
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
        return StreamingResponse(http_stream, media_type="application/x-ndjson")
    else:
        return await get_job_info(job)


async def get_ion_channel_build_status(job_id: UUID, *, job_queue: Queue) -> JobInfo:
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"message": "Job not found", "job_id": str(job_id)},
        )

    return await get_job_info(job)
