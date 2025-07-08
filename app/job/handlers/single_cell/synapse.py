import json
from uuid import UUID

from loguru import logger

from app.core.exceptions import SynapseGenerationError
from app.core.model import model_factory
from app.domains.morphology import SynapsePlacementBody
from app.external.entitycore.service import ProjectContext
from app.infrastructure.redis import stream_one
from app.infrastructure.rq import get_job_stream_key


def generate_synapses(
    model_id: UUID,
    params: SynapsePlacementBody,
    *,
    access_token: str,
    project_context: ProjectContext,
):
    stream_key = get_job_stream_key()

    try:
        model = model_factory(
            model_id,
            hyamp=None,
            access_token=access_token,
            project_context=project_context,
        )

        synapses = model.add_synapses(params)
        stream_one(stream_key, json.dumps(synapses))

    # TODO: add proper exception handlers
    except SynapseGenerationError as ex:
        logger.exception(f"Synapse generation error: {ex}")
        stream_one(stream_key, "error")
    except Exception as ex:
        logger.exception(f"Synapse generation error: {ex}")
        stream_one(stream_key, "error")
