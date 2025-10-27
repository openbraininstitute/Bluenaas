import asyncio
import time
from typing import Any, AsyncGenerator, Callable, Dict, Iterable, TypeVar
from uuid import uuid4

from loguru import logger
from rq import Queue, get_current_job
from rq.job import Job
from rq.job import JobStatus as RQJobStatus

from app.config.settings import settings
from app.core.job_stream import JobStatus, JobStream
from app.domains.stream_message import Message, MessageAdapter, MessageType
from app.infrastructure.redis.asyncio import redis_stream_reader
from app.utils.asyncio import run_async
from app.utils.streaming import compose_key

FunctionReferenceType = TypeVar("FunctionReferenceType", str, Callable[..., Any])


async def _job_status_monitor(
    job: Job,
    *,
    poll_interval: float = 3.0,
    on_start: Callable | None = None,
    on_success: Callable | None = None,
    on_failure: Callable | None = None,
):
    stream = JobStream(compose_key(job.id))

    last_queue_position: int | None = None
    last_status: RQJobStatus | None = None

    try:
        while True:
            # Stop monitoring if the job is in a terminal state.

            status = await run_async(lambda: job.get_status())

            match status:
                case RQJobStatus.SCHEDULED:
                    pass
                case RQJobStatus.DEFERRED:
                    pass
                case RQJobStatus.QUEUED:
                    position = await run_async(lambda: job.get_position())
                    if position and position != last_queue_position:
                        stream.send_status(JobStatus.pending, str(position))
                        last_queue_position = position
                case RQJobStatus.STARTED:
                    if on_start and status != last_status:
                        await on_start()
                case RQJobStatus.FAILED:
                    if on_failure:
                        await on_failure()
                    break
                case RQJobStatus.FINISHED:
                    if on_success:
                        await on_success()
                    break
                case _:
                    break

            last_status = status

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
    depends_on: Iterable[Job] | None = None,
    job_args: tuple = (),
    job_id: str | None = None,
    job_kwargs: dict = {},
    meta: dict = {},
    stream_ctx: Dict[str, Any] | None = None,
    on_failure: Callable[..., Any] | None = None,
    on_start: Callable[..., Any] | None = None,
    on_success: Callable[..., Any] | None = None,
    result_ttl: int | None = None,
    timeout: int = settings.MAX_JOB_DURATION,
) -> tuple[Job, AsyncGenerator[Any, Any]]:
    if job_id is None:
        job_id = str(uuid4())

    stream_key = compose_key(job_id)
    read_stream = redis_stream_reader(stream_key)

    write_stream = JobStream(stream_key, ctx=stream_ctx)

    job = await run_async(
        lambda: job_queue.enqueue(
            fn,
            *job_args,
            **job_kwargs,
            depends_on=depends_on,
            job_id=job_id,
            job_timeout=timeout,
            meta={
                **meta,
                "stream_ctx": stream_ctx,
            },
            result_ttl=result_ttl,
            # Default handlers only stream status updates
            on_failure=on_failure_default_handler,
            on_success=on_success_default_handler,
        ),
    )

    await run_async(lambda: write_stream.send_status(JobStatus.pending))

    asyncio.create_task(
        _job_status_monitor(job, on_start=on_start, on_failure=on_failure, on_success=on_success)
    )

    return job, read_stream


async def get_job_data(stream: AsyncGenerator[dict, None]):
    async for message_dict in stream:
        message: Message = MessageAdapter.validate_python(message_dict)

        if message.message_type == MessageType.status and message.status == JobStatus.error:
            raise RuntimeError("Job failed")

        if message.message_type == MessageType.data:
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
        await run_async(lambda: job.refresh())

        if job.is_finished:
            return job.result
        elif job.is_failed:
            raise RuntimeError(job.exc_info)

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Job {job.id} did not complete within {timeout} seconds")


def get_current_job_stream() -> JobStream:
    """Get the current job stream. Can be called only from a worker."""
    job = get_current_job()

    if job is None:
        raise ValueError("No job found")

    stream_key = compose_key(job.id)
    job_ctx = job.meta.get("stream_ctx")

    return JobStream(stream_key, ctx=job_ctx)
