import multiprocessing as mp
import signal
from http import HTTPStatus as status
from queue import Empty as QueueEmptyException
from uuid import UUID

from loguru import logger

from app.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    SynapseGenerationError,
)
from app.core.model import model_factory
from app.domains.morphology import (
    SynapsePlacementBody,
    SynapsePlacementResponse,
)
from app.external.entitycore.service import ProjectContext
from app.utils.const import QUEUE_STOP_EVENT


def _generate_synpases(
    model_id: str,
    token: str,
    params: SynapsePlacementBody,
    virtual_lab_id: str,
    project_id: str,
    is_entitycore,
    queue: mp.Queue,
    stop_event: mp.Event,  # type: ignore
):
    def stop_process(signum: int, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_process)
    signal.signal(signal.SIGINT, stop_process)

    try:
        model = model_factory(
            model_id=model_id,
            hyamp=None,
            bearer_token=token,
            entitycore=is_entitycore,
            project_context=ProjectContext(
                virtual_lab_id=UUID(virtual_lab_id),
                project_id=UUID(project_id),
            ),
        )

        synapses = model.add_synapses(params)
        queue.put(synapses)
        queue.put(QUEUE_STOP_EVENT)
    except SynapseGenerationError as ex:
        queue.put(ex)
    except Exception as ex:
        logger.exception(f"Synapses generator error: {ex}")
        raise SynapseGenerationError from ex
    finally:
        logger.debug("Synapses generator ended")


def generate_synapses_placement(
    model_id: str,
    token: str,
    req_id: str,
    params: SynapsePlacementBody,
    virtual_lab_id: str,
    project_id: str,
    is_entitycore: bool = False,
) -> SynapsePlacementResponse | None:
    try:
        ctx = mp.get_context("spawn")

        synapses_queue = ctx.Queue()
        stop_event = ctx.Event()
        process = ctx.Process(
            target=_generate_synpases,
            args=(
                model_id,
                token,
                params,
                virtual_lab_id,
                project_id,
                is_entitycore,
                synapses_queue,
                stop_event,
            ),
            name=f"synapses_processor:{req_id}",
        )
        process.daemon = True
        process.start()

        synapses = None
        try:
            while True:
                try:
                    record = synapses_queue.get(timeout=1)
                except QueueEmptyException:
                    if process.is_alive():
                        continue
                    if not synapses_queue.empty():
                        continue
                    else:
                        raise Exception("Child process died unexpectedly")
                if isinstance(record, SynapseGenerationError):
                    raise record
                if record == QUEUE_STOP_EVENT or stop_event.is_set():
                    break
                if record is not None:
                    synapses = record
                    break
        finally:
            synapses_queue.close()
            synapses_queue.join_thread()
            process.join()

        return synapses
    except SynapseGenerationError as ex:
        raise BlueNaasError(
            http_status_code=status.BAD_REQUEST,
            error_code=BlueNaasErrorCode.SYNAPSE_PLACEMENT_ERROR,
            message="generating synapses placement failed",
            details=ex.__str__(),
        ) from ex
    except Exception as ex:
        # logger.exception(f"generating synapses placement failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="generating synapses placement failed",
            details=ex.__str__(),
        ) from ex
