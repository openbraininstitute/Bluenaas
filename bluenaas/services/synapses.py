import signal
import multiprocessing as mp
from loguru import logger
from http import HTTPStatus as status

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.model import model_factory
from bluenaas.domains.morphology import SynapsePlacementBody, SynapsePlacementResponse
from bluenaas.utils.const import QUEUE_STOP_EVENT


def _generate_synpases(
    model_id: str,
    token: str,
    params: SynapsePlacementBody,
    queue: mp.Queue,
    stop_event: mp.Event
):
    def stop_process():
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_process)
    signal.signal(signal.SIGINT, stop_process)

    try:
        model = model_factory(
            model_id=model_id,
            bearer_token=token,
        )
        
        synapses = model.add_synapses(params)
        queue.put(synapses)

        queue.put(QUEUE_STOP_EVENT)
    except Exception as ex:
        logger.debug(f"Synapses generator error: {ex}")
    finally:
        logger.debug("Synapses generator ended")


def generate_synapses_placement(
    model_id: str,
    token: str,
    req_id: str,
    params: SynapsePlacementBody,
) -> SynapsePlacementResponse:
    try:
        synapses_queue = mp.Queue()
        stop_event = mp.Event()
        process = mp.Process(
            target=_generate_synpases,
            args=(
                model_id,
                token,
                params,
                synapses_queue,
                stop_event
            ),
            name=f"synapses_processor:{req_id}",
        )
        process.daemon = True
        process.start()

        synapses = None
        while True:
            record = synapses_queue.get()
            if record == QUEUE_STOP_EVENT or stop_event.is_set():
                break
            if record is not None:
                synapses = record
                break

        return synapses
    
    except Exception as ex:
        logger.error(f"generating synapses placement failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="generating synapses placement failed",
            details=ex.__str__(),
        ) from ex
