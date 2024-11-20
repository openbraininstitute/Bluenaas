import json
from loguru import logger

from bluenaas.infrastructure.celery import celery_app
from bluenaas.core.exceptions import SynapseGenerationError
from bluenaas.domains.morphology import SynapsePlacementBody


@celery_app.task(
    bind=True,
    serializer="json",
)
def place_synapses(
    self,
    model_self: str,
    token: str,
    synapse_placement_config: str,  # JSON string representing object of type StimulationPlotConfig
):
    try:
        from bluenaas.core.model import model_factory

        placement_config = SynapsePlacementBody(**json.loads(synapse_placement_config))

        logger.debug(f"Started placing synapses for model {model_self}")
        model = model_factory(
            model_self=model_self,
            hyamp=None,
            bearer_token=token,
        )
        synapses = model.add_synapses(params=placement_config)

        return synapses.model_dump_json()
    except Exception as e:
        logger.exception(f"Exception in celery worker during placing synapses {e}")
        raise SynapseGenerationError(message=f"Synaptome placement failed {e}")
    finally:
        logger.debug(f"Completed placing synapses for model {model_self}")
