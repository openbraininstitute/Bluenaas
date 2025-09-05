import json
import multiprocessing as mp
from itertools import chain
from multiprocessing.context import SpawnProcess
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from queue import Empty as QueueEmptyException
from uuid import UUID

from loguru import logger

from app.core.exceptions import (
    AppErrorCode,
    SimulationError,
)
from app.core.job_stream import JobStream
from app.core.model import fetch_synaptome_model_details
from app.domains.job import JobStatus
from app.domains.morphology import (
    SynapseConfig,
    SynapseSeries,
    SynapsesPlacementConfig,
)
from app.domains.simulation import (
    SingleNeuronSimulationConfig,
    SynapseSimulationConfig,
)
from app.external.entitycore.service import ProjectContext
from app.infrastructure.rq import get_job_stream_key
from app.utils.const import QUEUE_STOP_EVENT
from app.utils.util import log_stats_for_series_in_frequency


def init_current_varying_simulation(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    access_token: str,
    realtime: bool,
    simulation_queue: mp.Queue,
    stop_event: Event,
    project_context: ProjectContext,
):
    from app.core.model import model_factory

    try:
        me_model_id = model_id
        synapse_generation_config: list[SynapseSeries] | None = None

        if config.type == "synaptome-simulation" and config.synaptome is not None:
            synaptome_details = fetch_synaptome_model_details(
                bearer_token=access_token,
                model_id=model_id,
                project_context=project_context,
            )
            me_model_id = synaptome_details.base_model_id

        model = model_factory(
            me_model_id,
            hyamp=config.conditions.hypamp,
            access_token=access_token,
            project_context=project_context,
        )

        if config.type == "synaptome-simulation" and config.synaptome is not None:
            # only current injection simulation
            synapse_settings: list[list[SynapseSeries]] = []
            for index, synapse_sim_config in enumerate(config.synaptome):
                # 3. Get "pandas.Series" for each synapse
                synapse_placement_config = [
                    config
                    for config in synaptome_details.synaptome_placement_config.config  # type:ignore TODO Fix type
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

        if not model.CELL:
            raise RuntimeError("Model not initialized")

        model.CELL.start_current_varying_simulation(
            realtime=realtime,
            config=config,
            synapse_generation_config=synapse_generation_config,
            simulation_queue=simulation_queue,
            stop_event=stop_event,
        )
    except SimulationError as ex:
        simulation_queue.put(ex)
        simulation_queue.put(QUEUE_STOP_EVENT)
        raise ex
    except Exception as ex:
        logger.exception(f"Simulation executor error: {ex}")
        raise SimulationError from ex
    finally:
        logger.info("Simulation executor ended")


def get_constant_frequencies_for_sim_id(
    synapse_set_id: str, constant_frequency_sim_configs: list[SynapseSimulationConfig]
):
    constant_frequencies: list[float] = []
    for sim_config in constant_frequency_sim_configs:
        if sim_config.id == synapse_set_id and not isinstance(sim_config.frequency, list):
            constant_frequencies.append(sim_config.frequency)

    return constant_frequencies


def get_synapse_placement_config(
    sim_id: str, placement_configs: SynapsesPlacementConfig
) -> SynapseConfig:
    for placement_config in placement_configs.config:
        if placement_config.id == sim_id:
            return placement_config

    raise Exception(f"No synaptome placement config was found with id {sim_id}")


def get_sim_configs_by_synapse_id(
    sim_configs: list[SynapseSimulationConfig],
) -> dict[str, list[SynapseSimulationConfig]]:
    sim_id_to_sim_configs: dict[str, list[SynapseSimulationConfig]] = {}

    for sim_config in sim_configs:
        if sim_config.id in sim_id_to_sim_configs:
            sim_id_to_sim_configs[sim_config.id].append(sim_config)
        else:
            sim_id_to_sim_configs[sim_config.id] = [sim_config]

    return sim_id_to_sim_configs


def init_frequency_varying_simulation(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    access_token: str,
    realtime: bool,
    simulation_queue: mp.Queue,
    stop_event: Event,
    project_context: ProjectContext,
):
    from app.core.model import model_factory

    try:
        me_model_id = model_id
        synaptome_details = None
        if config.type == "synaptome-simulation" and config.synaptome is not None:
            synaptome_details = fetch_synaptome_model_details(
                bearer_token=access_token,
                model_id=model_id,
                project_context=project_context,
            )
            me_model_id = synaptome_details.base_model_id

        model = model_factory(
            me_model_id,
            hyamp=config.conditions.hypamp,
            access_token=access_token,
            project_context=project_context,
        )
        assert config.synaptome is not None

        variable_frequency_sim_configs: list[SynapseSimulationConfig] = []
        constant_frequency_sim_configs: list[SynapseSimulationConfig] = []

        # Split all incoming simulation configs into constant frequency or variable frequency sim configs
        for syn_sim_config in config.synaptome:
            if isinstance(syn_sim_config.frequency, list):
                variable_frequency_sim_configs.append(syn_sim_config)
            else:
                constant_frequency_sim_configs.append(syn_sim_config)

        frequency_to_synapse_settings: dict[float, list[SynapseSeries]] = {}

        offset = 0
        if synaptome_details is None:
            raise RuntimeError("synaptome_details is not initialized")
        for variable_frequency_sim_config in variable_frequency_sim_configs:
            synapse_placement_config = get_synapse_placement_config(
                variable_frequency_sim_config.id,
                synaptome_details.synaptome_placement_config,
            )

            frequency_list = variable_frequency_sim_config.frequency

            if not isinstance(frequency_list, list):
                frequency_list = [frequency_list]

            for frequency in frequency_list:
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

                sim_id_to_configs = get_sim_configs_by_synapse_id(constant_frequency_sim_configs)

                # Second, add synapse series for other sim configs of same synapse_set, but which have constant frequencies
                if variable_frequency_sim_config.id in sim_id_to_configs:
                    for sim_config in sim_id_to_configs[variable_frequency_sim_config.id]:
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

        if not model.CELL:
            raise RuntimeError("Model not initialized")

        model.CELL.start_frequency_varying_simulation(
            realtime=realtime,
            config=config,
            frequency_to_synapse_series=frequency_to_synapse_settings,
            simulation_queue=simulation_queue,
            stop_event=stop_event,
        )
    except SimulationError as ex:
        logger.exception(f"Simulation executor error: {ex}")
        simulation_queue.put(ex)
        simulation_queue.put(QUEUE_STOP_EVENT)
        raise ex
    except Exception as ex:
        logger.exception(f"Simulation executor error: {ex}")
        raise SimulationError from ex
    finally:
        logger.info("Simulation executor ended")


def is_current_varying_simulation(config: SingleNeuronSimulationConfig) -> bool:
    if config.type == "single-neuron-simulation" or config.synaptome is None:
        return True

    synapse_set_with_multiple_frequency = [
        synapse_set for synapse_set in config.synaptome if isinstance(synapse_set.frequency, list)
    ]
    if len(synapse_set_with_multiple_frequency) > 0:
        # TODO: This assertion should be at pydantic model level
        assert not isinstance(config.current_injection.stimulus.amplitudes, list)
        return False

    return True


def queue_record_to_stream_record(record: dict, is_current_varying: bool) -> dict:
    return {
        "x": record["time"],
        "y": record["voltage"],
        "type": "scatter",
        "name": record["label"],
        "recording": record["recording_name"],
        "amplitude": record["amplitude"],
        "frequency": record.get("frequency"),
        "current": record.get("current"),
        "varying_key": record["amplitude"] if is_current_varying is True else record["frequency"],
    }


def stream_realtime_data(
    simulation_queue: Queue,
    _process: SpawnProcess,
    is_current_varying: bool,
) -> None:
    stream_key = get_job_stream_key()
    job_stream = JobStream(stream_key)

    while True:
        try:
            # Simulation_Queue.get() is blocking. If child fails without writing to it,
            # the process will hang forever. That's why timeout is added.
            record = simulation_queue.get(timeout=1)
        except QueueEmptyException:
            if _process.is_alive():
                continue
            else:
                logger.warning("Process is not alive and simulation queue is empty")
                raise Exception("Child process died unexpectedly")
        if isinstance(record, SimulationError):
            errStr = json.dumps(
                {
                    "error_code": AppErrorCode.SIMULATION_ERROR,
                    "message": "Simulation failed",
                    "details": record.__str__(),
                }
            )
            job_stream.send_status(job_status=JobStatus.error, extra=errStr)
            logger.debug("Parent stopping because of error")
            break
        if record == QUEUE_STOP_EVENT:
            logger.debug("Parent received queue_stop_event")
            break

        chunk = queue_record_to_stream_record(record, is_current_varying)
        job_stream.send_data(chunk)

    logger.info("Realtime Simulation completed")
