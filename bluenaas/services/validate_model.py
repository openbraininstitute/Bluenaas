import io
import signal
import multiprocessing as mp
import sys
from loguru import logger
from http import HTTPStatus as status
from threading import Event
from queue import Empty as QueueEmptyException
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    ModelInitError,
)
from bluenaas.core.model import Model
from bluenaas.utils.const import QUEUE_STOP_EVENT


def _validate_model_draft(
    model_draft: dict,
    token: str,
    queue: mp.Queue,
    stop_event: Event,
):
    def stop_process():
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_process)
    signal.signal(signal.SIGINT, stop_process)

    # Create a string buffer to capture stderr output
    stderr_buffer = io.StringIO()
    sys.stderr = stderr_buffer  # Redirect stderr to the buffer

    try:
        Model.validate(model_draft, token)
        queue.put(QUEUE_STOP_EVENT)

    except Exception:
        error_message = stderr_buffer.getvalue().strip()
        queue.put(ModelInitError(error_message))
        queue.put(QUEUE_STOP_EVENT)

    finally:
        sys.stderr = sys.__stderr__  # Restore original stderr


def validate_model_draft(
    model_draft: dict,
    token: str,
    req_id: str,
):
    try:
        ctx = mp.get_context("spawn")

        result_queue = ctx.Queue()
        stop_event = ctx.Event()

        process = ctx.Process(
            target=_validate_model_draft,
            args=(
                model_draft,
                token,
                result_queue,
                stop_event,
            ),
            name=f"model_draft_validation_processor:{req_id}",
        )
        process.daemon = True
        process.start()

        exc = None

        try:
            while True:
                try:
                    q_result = result_queue.get(timeout=1)
                except QueueEmptyException:
                    if process.is_alive():
                        continue
                    if not result_queue.empty():
                        continue
                    else:
                        raise Exception("Child process died unexpectedly")
                logger.info(f"Result: {q_result}")
                if isinstance(q_result, ModelInitError):
                    exc = q_result

                if q_result == QUEUE_STOP_EVENT or stop_event.is_set():
                    break
        finally:
            result_queue.close()
            result_queue.join_thread()
            process.join()

        if exc is not None:
            raise exc
    except Exception as ex:
        raise BlueNaasError(
            http_status_code=status.UNPROCESSABLE_ENTITY,
            error_code=BlueNaasErrorCode.MODEL_INIT_ERROR,
            message="Model draft validation failed",
            details=ex.__str__(),
        ) from ex
