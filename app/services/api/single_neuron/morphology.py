from uuid import UUID

from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse
from rq import Queue

from app.external.entitycore.service import ProjectContext
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch, get_job_data


async def get_morphology_stream(
    model_id: UUID,
    *,
    request: Request,
    job_queue: Queue,
    access_token: str,
    project_context: ProjectContext | None = None,
) -> JSONResponse:
    _job, stream = await dispatch(
        job_queue,
        JobFn.GET_MORPHOLOGY,
        job_args=(model_id,),
        job_kwargs={"access_token": access_token, "project_context": project_context},
    )

    morphology = await get_job_data(stream)

    return JSONResponse(morphology)


async def get_morphology_dendrogram(
    model_id: UUID,
    *,
    request: Request,
    job_queue: Queue,
    access_token: str,
) -> StreamingResponse:
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = await dispatch(
        job_queue,
        JobFn.GET_MORPHOLOGY_DENDROGRAM,
        job_args=(model_id, access_token),
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
