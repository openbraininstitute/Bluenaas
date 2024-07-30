import json
import re
import signal
import multiprocessing as mp
from fastapi.responses import StreamingResponse
from loguru import logger
from http import HTTPStatus as status
from threading import Event

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.model import model_factory
from bluenaas.utils.const import QUEUE_STOP_EVENT


def _build_morphology(
    model_id: str,
    token: str,
    queue: mp.Queue,
    stop_event: Event,
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
        morphology = model.CELL.get_cell_morph()
        morph_str = json.dumps(morphology)
        chunks: list[str] = re.findall(r".{1,100000}", morph_str)

        for index, chunk in enumerate(chunks):
            logger.debug(f"Queueing chunk {index} for morphology...")
            queue.put(chunk)

        queue.put(QUEUE_STOP_EVENT)

    except Exception as ex:
        logger.debug(f"Morphology builder error: {ex}")
    finally:
        logger.debug("Morphology builder ended")


def get_single_morphology(
    model_id: str,
    token: str,
    req_id: str,
):
    try:
        morpho_queue = mp.Queue()
        stop_event = mp.Event()

        process = mp.Process(
            target=_build_morphology,
            args=(
                model_id,
                token,
                morpho_queue,
                stop_event,
            ),
            name=f"morphology_processor:{req_id}",
        )
        process.daemon = True
        process.start()

        def queue_streamify(
            que: mp.Queue,
            stop_event: Event,
        ):
            while True:
                q_result = que.get()

                if q_result == QUEUE_STOP_EVENT or stop_event.is_set():
                    break

                yield q_result

        return StreamingResponse(
            queue_streamify(
                que=morpho_queue,
                stop_event=stop_event,
            ),
            media_type="application/x-ndjson",
        )

    except Exception as ex:
        logger.error(f"retrieving morphology data failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="retrieving morphology data failed",
            details=ex.__str__(),
        ) from ex
