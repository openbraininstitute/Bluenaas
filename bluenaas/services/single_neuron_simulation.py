import json
import multiprocessing as mp
from itertools import chain
from loguru import logger
from http import HTTPStatus as status
from fastapi.responses import StreamingResponse
from queue import Empty as QueueEmptyException

from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    BlueNaasErrorResponse,
    SimulationError,
)
from bluenaas.core.model import fetch_synaptome_model_details
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import SingleNeuronSimulationConfig
from bluenaas.utils.const import QUEUE_STOP_EVENT


def _init_simulation(
    model_id: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    simulation_queue: mp.Queue,
    req_id: str,
):
    from bluenaas.core.model import model_factory

    try:
        me_model_id = model_id
        synapse_generation_config: list[SynapseSeries] = None

        if config.type == "synaptome-simulation" and config.synapses is not None:
            # and model.resource.type:
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

                synapses_per_grp = model.get_synapse_series(
                    synapse_placement_config=synapse_placement_config,
                    synapse_simulation_config=synapse_sim_config,
                    offset=index,
                )

                synapse_settings.append(synapses_per_grp)

            synapse_generation_config = list(chain.from_iterable(synapse_settings))

        model.CELL.start_simulation(
            config=config,
            synapse_generation_config=synapse_generation_config,
            simulation_queue=simulation_queue,
            req_id=req_id,
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


def execute_single_neuron_simulation(
    model_id: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    req_id: str,
):
    try:
        ctx = mp.get_context("spawn")
        simulation_queue = ctx.Queue()

        _process = ctx.Process(
            target=_init_simulation,
            args=(
                model_id,
                token,
                config,
                simulation_queue,
                req_id,
            ),
            name=f"simulation_processor:{req_id}",
        )
        _process.start()

        def queue_streamify():
            while True:
                try:
                    # Simulation_Queue.get() is blocking. If child fails without writing to it,
                    # the process will hang forever. That's why timeout is added.
                    record = simulation_queue.get(timeout=1)
                except QueueEmptyException:
                    if _process.is_alive():
                        continue
                    else:
                        logger.warning(
                            "Process is not alive and simulation queue is empty"
                        )
                        raise Exception("Child process died unexpectedly")
                if isinstance(record, SimulationError):
                    yield f"{json.dumps(
                        {
                            "error_code": BlueNaasErrorCode.SIMULATION_ERROR,
                            "message": "Simulation failed",
                            "details": record.__str__(),
                        }
                    )}\n"
                    break
                if record == QUEUE_STOP_EVENT:
                    break

                (stimulus_name, recording_name, amplitude, recording) = record

                logger.info(
                    f"[R/S --> {recording_name}/{stimulus_name}]",
                )
                yield f"{json.dumps(
                    {
                        "amplitude": amplitude,
                        "stimulus_name": stimulus_name,
                        "recording_name": recording_name,
                        "t": list(recording.time),
                        "v": list(recording.voltage),
                    }
                )}\n"

            logger.info(f"Simulation {req_id} completed")

        return StreamingResponse(
            queue_streamify(),
            media_type="application/octet-stream",
        )
    except Exception as ex:
        logger.exception(f"running simulation failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="running simulation failed",
            details=ex.__str__(),
        ) from ex
