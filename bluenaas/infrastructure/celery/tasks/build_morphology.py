import json
from loguru import logger

from bluenaas.infrastructure.celery import celery_app
from bluenaas.core.exceptions import MorphologyGenerationError


@celery_app.task(
    bind=True,
    serializer="json",
)
def build_morphology(
    self,
    model_self: str,
    token: str,
):
    try:
        from bluenaas.core.model import model_factory

        logger.debug(f"Started building morphology for model {model_self}")
        model = model_factory(
            model_self=model_self,
            hyamp=None,
            bearer_token=token,
        )
        morphology = model.CELL.get_cell_morph()
        morph_str = json.dumps(morphology)

        logger.debug(f"Completed building morphology for model {model_self}")
        return morph_str
    except Exception as e:
        logger.exception(f"Exception in celery worker during morphology building {e}")
        raise MorphologyGenerationError(message=f"Morphology generation failed {e}")
