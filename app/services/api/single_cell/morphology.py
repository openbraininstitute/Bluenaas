from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.external.entitycore.service import ProjectContext
from app.job import JobFn
from app.utils.rq_job import dispatch
from app.utils.streaming import x_ndjson_http_stream


def get_morphology_stream(
    request: Request,
    queue: Queue,
    model_id: str,
    token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = dispatch(
        queue,
        JobFn.GET_MORPHOLOGY,
        job_args=(model_id, token, entitycore, project_context),
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")


def get_morphology_dendrogram(
    request: Request,
    queue: Queue,
    model_id: str,
    token: str,
):
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = dispatch(
        queue,
        JobFn.GET_MORPHOLOGY_DENDROGRAM,
        job_args=(model_id, token),
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
