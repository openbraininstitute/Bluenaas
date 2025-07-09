from uuid import UUID

from loguru import logger

from app.core.job_stream import JobStream
from app.core.model import model_factory
from app.domains.morphology import SynapsePlacementBody
from app.external.entitycore.service import ProjectContext
from app.infrastructure.rq import get_job_stream_key


def generate_synapses(
    model_id: UUID,
    params: SynapsePlacementBody,
    *,
    access_token: str,
    project_context: ProjectContext,
):
    stream_key = get_job_stream_key()
    job_stream = JobStream(stream_key)

    try:
        model = model_factory(
            model_id,
            hyamp=None,
            access_token=access_token,
            project_context=project_context,
        )

        synapses = model.add_synapses(params)
        job_stream.send_data(synapses)

    except Exception as ex:
        logger.exception(f"Synapse generation error: {ex}")
        raise
