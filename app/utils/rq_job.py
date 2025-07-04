import asyncio
import json
import time
from typing import Any, AsyncGenerator, Callable, TypeVar
from uuid import uuid4

from loguru import logger
from rq import Queue
from rq.job import Job
from rq.job import JobStatus as RQJobStatus

from app.config.settings import settings
from app.core.job_stream import JobStatus, JobStream
from app.infrastructure.redis import stream
from app.infrastructure.redis.asyncio import redis_stream_reader
from app.utils.streaming import compose_key

FunctionReferenceType = TypeVar("FunctionReferenceType", str, Callable[..., Any])


async def _stream_queue_position(job: Job, poll_interval: float = 3.0):
    stream_key = compose_key(job.id)

    prev_position = None

    try:
        while True:
            # Stop monitoring if job is no longer queued
            if job.get_status() != RQJobStatus.QUEUED:
                break

            # Get current queue position
            position = job.get_position()

            if position != prev_position:
                msg = {"status": "queued", "extra": position}
                stream(stream_key, json.dumps(msg))
                prev_position = position

            await asyncio.sleep(poll_interval)

    except Exception as e:
        # Log error but don't crash the thread
        logger.error(f"Error monitoring queue position for job {job.id}: {e}")


def on_failure(job, connection, exc_type, exc_value, traceback):
    stream = JobStream(compose_key(job.id))

    stream.send_status(JobStatus.error, str(exc_value))
    stream.close()


def on_success(job, connection, result):
    stream = JobStream(compose_key(job.id))

    stream.send_status(JobStatus.done)
    stream.close()


async def dispatch(
    queue: Queue,
    fn: FunctionReferenceType,
    job_args: tuple = (),
    job_kwargs: dict = {},
    job_id: str | None = None,
    timeout: int = settings.MAX_JOB_DURATION,
    stream_queue_position: bool = False,
    position_poll_interval: float = 1.0,
) -> tuple[Job, AsyncGenerator[Any, Any]]:
    if job_id is None:
        job_id = str(uuid4())

    stream_key = compose_key(job_id)
    read_stream = redis_stream_reader(stream_key)

    write_stream = JobStream(stream_key)

    # Run the blocking queue.enqueue call in a separate thread
    loop = asyncio.get_event_loop()
    job = await loop.run_in_executor(
        None,
        lambda: queue.enqueue(
            fn,
            *job_args,
            **job_kwargs,
            job_id=job_id,
            job_timeout=timeout,
            on_failure=on_failure,
            on_success=on_success,
        ),
    )

    await loop.run_in_executor(
        None, lambda: write_stream.send_status(JobStatus.pending)
    )

    if stream_queue_position:
        asyncio.create_task(_stream_queue_position(job, position_poll_interval))

    return job, read_stream


async def wait_for_job(
    job: Job, timeout: int = settings.MAX_JOB_DURATION, poll_interval: float = 2.0
) -> Any:
    """
    Wait for an RQ job to finish with a timeout.

    Args:
        job: The RQ job to wait for
        timeout: Maximum time to wait in seconds
        poll_interval: How often to check job status in seconds

    Returns:
        The job result if successful

    Raises:
        TimeoutError: If the job doesn't complete within the timeout
        Exception: If the job fails, the original exception is re-raised
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        # Run the blocking job.refresh call in a separate thread
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, job.refresh)

        if job.is_finished:
            return job.result
        elif job.is_failed:
            raise job.exc_info

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Job {job.id} did not complete within {timeout} seconds")
