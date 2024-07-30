import json
import signal
import multiprocessing as mp
from loguru import logger
from threading import Event
from http import HTTPStatus as status
from fastapi.responses import StreamingResponse

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.domains.simulation import SimulationConfigBody
from bluenaas.utils.const import QUEUE_STOP_EVENT


def _init_simulation(
    model_id: str,
    token: str,
    config: SimulationConfigBody,
    simulation_queue: mp.Queue,
    stop_event: Event,
    req_id: str,
):
    from bluenaas.core.model import model_factory
    # TODO: this stop_process fail when running multiple sims, to debug;
    def stop_process():
        # TODO: kill the process when event is_set in the handler
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_process)
    signal.signal(signal.SIGINT, stop_process)

    try:
        model = model_factory(
            model_id=model_id,
            bearer_token=token,
        )
        model.CELL.set_injection_location(config.injectTo)
        model.CELL.start_simulation(
            config=config,
            simulation_queue=simulation_queue,
            req_id=req_id
        )

    except Exception as ex:
        logger.debug(f"Simulation executor error: {ex}")
    finally:
        logger.debug("Simulation executor ended")


def execute_simulation(
    model_id: str,
    token: str,
    config: SimulationConfigBody,
    req_id: str,
):
    try:
        simulation_queue = mp.Queue()
        stop_event = mp.Event()

        pro = mp.Process(
            target=_init_simulation,
            args=(
                model_id,
                token,
                config,
                simulation_queue,
                stop_event,
                req_id
            ),
            name=f"simulation_processor:{req_id}",
        )
        pro.start()

        def queue_streamify():
            while True:
                record = simulation_queue.get()
                # TODO: probably using queue.empty() will be enough
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
