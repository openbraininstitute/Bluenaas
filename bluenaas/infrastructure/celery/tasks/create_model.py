from itertools import chain
import json
from loguru import logger


from bluenaas.core.model import fetch_synaptome_model_details
from bluenaas.infrastructure.celery import celery_app
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from bluenaas.utils.serializer import (
    serialize_template_params,
)


@celery_app.task(
    bind=True,
    serializer="json",
    queue="builder"
)
def create_model(
    self,
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
):
    logger.info("[create_model]")
    from bluenaas.core.model import model_factory

    cf = SingleNeuronSimulationConfig(**json.loads(config))
    me_model_id = model_self

    if cf.type == "synaptome-simulation" and cf.synaptome is not None:
        synaptome_details = fetch_synaptome_model_details(
            synaptome_self=model_self, bearer_token=token
        )
        me_model_id = synaptome_details.base_model_self

    model = model_factory(
        model_self=me_model_id,
        hyamp=cf.conditions.hypamp,
        bearer_token=token,
    )
    cell = model.CELL._cell
    template_params = cell.template_params
    synapse_generation_config: list[SynapseSeries] = None

    if cf.type == "synaptome-simulation" and cf.synaptome is not None:
        # only current injection simulation
        synapse_settings: list[list[SynapseSeries]] = []
        for index, synapse_sim_config in enumerate(cf.synaptome):
            # 3. Get "pandas.Series" for each synapse
            synapse_placement_config = [
                config
                for config in synaptome_details.synaptome_placement_config.config
                if synapse_sim_config.id == config.id
            ][0]

            assert not isinstance(synapse_sim_config.frequency, list)
            synapses_per_grp = model.get_synapse_series(
                synapse_placement_config=synapse_placement_config,
                synapse_simulation_config=synapse_sim_config,
                offset=index,
                frequencies_to_apply=[synapse_sim_config.frequency],
            )

            synapse_settings.append(synapses_per_grp)

        synapse_generation_config = list(chain.from_iterable(synapse_settings))
    logger.info(f"@@-> {template_params=}")
    logger.info(f"@@-> {synapse_generation_config=}")
    return (serialize_template_params(template_params), synapse_generation_config)
