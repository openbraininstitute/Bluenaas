import json

from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from rq import Queue

from bluenaas.core.model import model_factory
from bluenaas.external.entitycore.service import ProjectContext
from bluenaas.infrastructure.redis import stream_one
from bluenaas.infrastructure.rq import get_current_stream_key
from bluenaas.utils.rq_job import dispatch
from bluenaas.utils.streaming import x_ndjson_http_stream


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
        get_morphology_task,
        job_args=(model_id, token, entitycore, project_context),
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")


def get_morphology_task(
    model_id: str,
    token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    stream_key = get_current_stream_key()
    logger.info(f"Stream key: {stream_key}")

    try:
        model = model_factory(
            model_id=model_id,
            hyamp=None,
            entitycore=entitycore,
            bearer_token=token,
            project_context=project_context,
        )

        if not model.CELL:
            raise RuntimeError(f"Model hasn't been initialized: {model_id}")

        morphology = model.CELL.get_cell_morph()
        stream_one(stream_key, json.dumps(morphology))

    except Exception as ex:
        logger.exception(f"Morphology builder error: {ex}")
        stream_one(stream_key, "error")
        # TODO: put exception in the queue
