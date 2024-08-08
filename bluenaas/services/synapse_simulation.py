import json
import multiprocessing as mp

from queue import Empty as QueueEmptyException
from loguru import logger
from http import HTTPStatus as status
from fastapi.responses import StreamingResponse
from timeit import default_timer as timer
from threading import Event
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.model import fetch_synaptome_model_details
from bluenaas.domains.simulation import SimulationWithSynapseBody
from bluenaas.utils.const import QUEUE_STOP_EVENT


def _init_simulation(
    synaptome_self: str,
    token: str,
    params: SimulationWithSynapseBody,
    simulation_queue: mp.Queue,
    stop_event: Event,
):
    from bluenaas.core.model import model_factory

    try:
        # 1. Fetch me-model id and synaptome_placement_config
        synaptome_details = fetch_synaptome_model_details(
            synaptome_self=synaptome_self, bearer_token=token
        )
        # 2. Build model
        model = model_factory(
            model_id=synaptome_details.base_model_self,
            bearer_token=token,
        )

        print("PLACEMENT_CONFIGS", synaptome_details.synaptome_placement_config.config)
        print("SIM CNFIGs", params.synapseConfigs)
        for index, synapse_sim_config in enumerate(params.synapseConfigs):
            # 3. Get "pandas.Series" for each synapse
            synapse_placement_config = [
                config
                for config in synaptome_details.synaptome_placement_config.config
                if synapse_sim_config.id == config.id
            ][0]

            synapses_for_config = model.get_synapse_series(
                global_seed=synaptome_details.synaptome_placement_config.seed,
                placement_config=synapse_placement_config,
                simulation_config=synapse_sim_config,
                offset=index,
            )
            print(
                f"_____Total Synapses in group {synapse_sim_config.id}_____",
                len(synapses_for_config),
            )

            # 4. Add synapses to cell
            start = timer()
            model.CELL.add_synapses_to_cell(
                synapses_for_config, params.directCurrentConfig, synapse_sim_config
            )
            end = timer()
            print(
                f"Adding {len(synapses_for_config)} synapses took {end-start} seconds"
            )

        # cores_available = len(os.sched_getaffinity(0))
        # synapse_chunks = np.array_split(limited_synapses, cores_available)
        # with mp.Pool() as pool:
        #     pool.starmap(model.CELL.add_synapses_to_cell, (synapse_chunks))

        print("TOTAL_SYNAPSES", len(model.CELL._cell.synapses))
        print("TOTAL_CONNECTIONS", len(model.CELL._cell.connections))

        # 5. Start simulation with synapses
        start = timer()
        model.CELL.start_synapse_simulation(queue=simulation_queue)
        end = timer()
        print(f"Running simulation took {end-start} seconds")
    except Exception as ex:
        logger.debug(f"Simulation executor error: {ex}")
        raise Exception(ex)
    finally:
        logger.debug("Simulation executor ended")


def execute_synapse_simulation(
    model_id: str,
    token: str,
    params: SimulationWithSynapseBody,
    req_id: str,
):
    try:
        simulation_queue: mp.Queue = mp.Queue()
        stop_event = mp.Event()

        pro = mp.Process(
            target=_init_simulation,
            args=(model_id, token, params, simulation_queue, stop_event),
            name=f"simulation_processor:{req_id}",
        )
        pro.start()

        def queue_streamify():
            while True:
                try:
                    # Simulation_Queue.get() is blocking. If child fails without writing to it, the process will hang forever. That's why timeout is added.
                    record = simulation_queue.get(timeout=1)  # 1 second
                except QueueEmptyException:
                    if pro.is_alive():
                        continue
                    if not simulation_queue.empty():
                        # Checking if queue is empty again to avoid the following race condition:
                        # t0 - Empty exception is raised from queue.get()
                        # t1 - Child process writes to queue
                        # t2 - Child process finishes
                        # t3 - Queue should be checked again for emptiness to capture the last message
                        continue
                    else:
                        raise Exception("Child process died unexpectedly")
                if record == QUEUE_STOP_EVENT or stop_event.is_set():
                    break

                (stimulus_name, recording) = record

                yield json.dumps(
                    {
                        "t": list(recording.time),
                        "v": list(recording.voltage),
                        "name": stimulus_name,
                    }
                )

        return StreamingResponse(
            queue_streamify(),
            media_type="application/x-ndjson",
        )

    except Exception as ex:
        logger.error(f"running simulation failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="running simulation failed",
            details=ex.__str__(),
        ) from ex
