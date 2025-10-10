import json
from uuid import UUID

from entitysdk import ProjectContext
from loguru import logger

from app.core.job_stream import JobStream
from app.core.model import model_factory
from app.domains.job import JobStatus
from app.infrastructure.rq import get_job_stream_key


def get_morphology(
    model_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
):
    job_stream = JobStream(get_job_stream_key(), ttl=20)

    try:
        model = model_factory(
            model_id,
            hyamp=None,
            access_token=access_token,
            project_context=project_context,
        )

        if not model.CELL:
            raise RuntimeError(f"Model hasn't been initialized: {model_id}")

        morphology = model.CELL.get_cell_morph()

        job_stream.send_data_once(morphology)

    except Exception as ex:
        logger.exception(f"Morphology builder error: {ex}")
        raise


def get_morphology_dendrogram(
    model_id: UUID, *, access_token: str, project_context: ProjectContext
):
    job_stream = JobStream(get_job_stream_key(), ttl=20)

    try:
        model = model_factory(
            model_id,
            hyamp=None,
            access_token=access_token,
            project_context=project_context,
        )

        if not model.CELL:
            raise RuntimeError("Model not initialized")

        morphology_dendrogram = model.CELL.get_dendrogram()
        job_stream.send_data_once(morphology_dendrogram)

    # TODO: propagate error to the stream
    except Exception as ex:
        logger.exception(f"Morphology dendrogram builder error: {ex}")
        job_stream.send_status(JobStatus.error, str(ex))
