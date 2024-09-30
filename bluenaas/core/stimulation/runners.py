from loguru import logger
from bluenaas.core.stimulation.common import (
    get_constant_frequencies_for_sim_id,
    get_sim_configs_by_synapse_id,
    get_synapse_placement_config,
)
from itertools import chain
from bluenaas.utils.util import log_stats_for_series_in_frequency

from bluenaas.core.exceptions import SimulationError
from bluenaas.core.model import fetch_synaptome_model_details
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    SynapseSimulationConfig,
)


def _init_current_varying_simulation(
    model_id: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    req_id: str,
):
    from bluenaas.core.model import model_factory

    try:
        me_model_id = model_id
        synapse_generation_config: list[SynapseSeries] = None

        if config.type == "synaptome-simulation" and config.synapses is not None:
            synaptome_details = fetch_synaptome_model_details(
                synaptome_self=model_id, bearer_token=token
            )
            me_model_id = synaptome_details.base_model_self

        model = model_factory(
            model_id=me_model_id,
            hyamp=config.conditions.hypamp,
            bearer_token=token,
        )

        if config.type == "synaptome-simulation" and config.synapses is not None:
            # only current injection simulation
            synapse_settings: list[list[SynapseSeries]] = []
            for index, synapse_sim_config in enumerate(config.synapses):
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

        return model.CELL.start_current_varying_simulation(
            config=config,
            synapse_generation_config=synapse_generation_config,
            req_id=req_id,
        )
    except SimulationError as ex:
        raise ex
    except Exception as ex:
        logger.exception(f"Simulation executor error: {ex}")
        raise SimulationError from ex
    finally:
        logger.info("Simulation executor ended")


def _init_frequency_varying_simulation(
    model_id: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    req_id: str,
):
    from bluenaas.core.model import model_factory

    try:
        me_model_id = model_id
        synaptome_details = fetch_synaptome_model_details(
            synaptome_self=model_id, bearer_token=token
        )
        me_model_id = synaptome_details.base_model_self

        model = model_factory(
            model_id=me_model_id,
            hyamp=config.conditions.hypamp,
            bearer_token=token,
        )
        assert config.synapses is not None

        variable_frequency_sim_configs: list[SynapseSimulationConfig] = []
        constant_frequency_sim_configs: list[SynapseSimulationConfig] = []

        # Split all incoming simulation configs into constant frequency or variable frequency sim configs
        for syn_sim_config in config.synapses:
            if isinstance(syn_sim_config.frequency, list):
                variable_frequency_sim_configs.append(syn_sim_config)
            else:
                constant_frequency_sim_configs.append(syn_sim_config)

        frequency_to_synapse_settings: dict[float, list[SynapseSeries]] = {}

        offset = 0
        for variable_frequency_sim_config in variable_frequency_sim_configs:
            synapse_placement_config = get_synapse_placement_config(
                variable_frequency_sim_config.id,
                synaptome_details.synaptome_placement_config,
            )

            for frequency in variable_frequency_sim_config.frequency:
                frequency_to_synapse_settings[frequency] = []

                frequencies_to_apply = get_constant_frequencies_for_sim_id(
                    variable_frequency_sim_config.id, constant_frequency_sim_configs
                )
                frequencies_to_apply.append(frequency)

                # First, add synapse_series for sim_config with this variable frequency
                frequency_to_synapse_settings[frequency].extend(
                    model.get_synapse_series(
                        synapse_placement_config,
                        variable_frequency_sim_config,
                        offset,
                        frequencies_to_apply,
                    )
                )
                offset += 1

                sim_id_to_configs = get_sim_configs_by_synapse_id(
                    constant_frequency_sim_configs
                )

                # Second, add synapse series for other sim configs of same synapse_set, but which have constant frequencies
                if variable_frequency_sim_config.id in sim_id_to_configs:
                    for sim_config in sim_id_to_configs[
                        variable_frequency_sim_config.id
                    ]:
                        frequency_to_synapse_settings[frequency].extend(
                            model.get_synapse_series(
                                synapse_placement_config,
                                sim_config,
                                offset,
                                frequencies_to_apply,
                            )
                        )
                        offset += 1
                    # Since all synapses for variable_frequency_sim_config are now added, remove it from the dictionary
                    sim_id_to_configs.pop(variable_frequency_sim_config.id)

                # Finally, add synapse series for all other sim configs from different synapse_sets (these should have constant frequencies)
                for index, sim_id in enumerate(sim_id_to_configs):
                    sim_configs_for_set = sim_id_to_configs[sim_id]
                    constant_frequencies_for_set = get_constant_frequencies_for_sim_id(
                        sim_id, sim_configs_for_set
                    )
                    placement_config_for_set = get_synapse_placement_config(
                        sim_id, synaptome_details.synaptome_placement_config
                    )

                    for sim_config in sim_configs_for_set:
                        frequency_to_synapse_settings[frequency].extend(
                            model.get_synapse_series(
                                placement_config_for_set,
                                sim_config,
                                offset,
                                constant_frequencies_for_set,
                            )
                        )
                        offset += 1

        for frequency in frequency_to_synapse_settings:
            logger.debug(
                f"Constructed {len(frequency_to_synapse_settings[frequency])} synapse series for frequency {frequency}"
            )
            log_stats_for_series_in_frequency(frequency_to_synapse_settings[frequency])

        model.CELL.start_frequency_varying_simulation(
            config=config,
            frequency_to_synapse_series=frequency_to_synapse_settings,
            # simulation_queue=simulation_queue,
            req_id=req_id,
        )
    except SimulationError as ex:
        logger.exception(f"Simulation executor error: {ex}")
        # simulation_queue.put(ex)
        # simulation_queue.put(QUEUE_STOP_EVENT)
        raise ex
    except Exception as ex:
        logger.exception(f"Simulation executor error: {ex}")
        raise SimulationError from ex
    finally:
        logger.info("Simulation executor ended")
