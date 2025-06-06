import json

from loguru import logger

from app.core.model import model_factory
from app.external.entitycore.service import ProjectContext
from app.infrastructure.redis import stream_one
from app.infrastructure.rq import get_current_stream_key


def get_morphology(
    model_id: str,
    token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    stream_key = get_current_stream_key()

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
