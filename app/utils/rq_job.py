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
from app.domains.job import JobMessage, JobMessageAdapter, JobMessageType
from app.infrastructure.redis.asyncio import redis_stream_reader
from app.utils.asyncio import run_async
from app.utils.streaming import compose_key

FunctionReferenceType = TypeVar("FunctionReferenceType", str, Callable[..., Any])


async def _job_status_monitor(
    job: Job,
    *,
    poll_interval: float = 3.0,
    on_success: Callable | None = None,
    on_failure: Callable | None = None,
):
    stream = JobStream(compose_key(job.id))

    prev_position = None

    try:
        while True:
            # Stop monitoring if job is no longer queued

            status = await run_async(lambda: job.get_status())

            if status == RQJobStatus.FAILED and on_failure:
                on_failure()
                break
            elif status == RQJobStatus.FINISHED and on_success:
                on_success()
                break
            elif status != RQJobStatus.QUEUED:
                break

            # Get current queue position
            position = job.get_position()

            if position and position != prev_position:
                stream.send_status(JobStatus.pending, str(position))
                prev_position = position

            await asyncio.sleep(poll_interval)

    except Exception as e:
        # Log error but don't crash the thread
        logger.error(f"Error monitoring job status for job {job.id}: {e}")


def on_failure_default_handler(job, connection, exc_type, exc_value, traceback):
    stream = JobStream(compose_key(job.id))

    logger.error(
        f"Job {job.id} failed with {exc_type.__name__}: {exc_value}",
        exc_info=(exc_type, exc_value, traceback),
    )

    stream.send_status(JobStatus.error, str(exc_value))
    stream.close()


def on_success_default_handler(job, connection, result):
    stream = JobStream(compose_key(job.id))

    stream.send_status(JobStatus.done)
    stream.close()


async def dispatch(
    job_queue: Queue,
    fn: FunctionReferenceType,
    *,
    job_args: tuple = (),
    job_kwargs: dict = {},
    job_id: str | None = None,
    timeout: int = settings.MAX_JOB_DURATION,
    meta: dict | None = None,
    depends_on: Job | None = None,
    on_failure: Callable[..., Any] | None = None,
    on_success: Callable[..., Any] | None = None,
) -> tuple[Job, AsyncGenerator[Any, Any]]:
    if job_id is None:
        job_id = str(uuid4())

    stream_key = compose_key(job_id)
    read_stream = redis_stream_reader(stream_key)

    write_stream = JobStream(stream_key)

    job = await run_async(
        lambda: job_queue.enqueue(
            fn,
            *job_args,
            **job_kwargs,
            job_id=job_id,
            job_timeout=timeout,
            depends_on=depends_on,
            meta=meta,
            # Default handlers only stream status updates
            on_failure=on_failure_default_handler,
            on_success=on_success_default_handler,
        ),
    )

    await run_async(lambda: write_stream.send_status(JobStatus.pending))

    asyncio.create_task(_job_status_monitor(job, on_success=on_success, on_failure=on_failure))

    return job, read_stream


async def get_job_data(stream: AsyncGenerator[str, None]):
    async for message_str in stream:
        message: JobMessage = JobMessageAdapter.validate_json(message_str)

        if message.message_type == JobMessageType.status and message.status == JobStatus.error:
            raise RuntimeError("Job failed")

        if message.message_type == JobMessageType.data:
            return message.data

    raise RuntimeError("Job never sent any data")


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
            raise RuntimeError(job.exc_info)

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Job {job.id} did not complete within {timeout} seconds")
