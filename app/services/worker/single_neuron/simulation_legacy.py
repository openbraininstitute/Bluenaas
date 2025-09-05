# This file contains legacy simulation functions that have been replaced by unified_simulation.py
# These functions are kept temporarily for reference and will be removed once the refactor is complete

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


# All functions below have been moved to unified_simulation.py and are no longer used


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
