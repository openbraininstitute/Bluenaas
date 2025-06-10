import time
from typing import Any, AsyncGenerator, Callable, TypeVar
from uuid import uuid4

from rq import Queue
from rq.job import Job

from app.constants import MAX_JOB_DURATION
from app.infrastructure.redis.async_redis import redis_stream_reader
from app.utils.streaming import compose_key

FunctionReferenceType = TypeVar("FunctionReferenceType", str, Callable[..., Any])


def dispatch(
    queue: Queue,
    fn: FunctionReferenceType,
    job_args: tuple = (),
    job_kwargs: dict = {},
    job_id: str | None = None,
) -> tuple[Job, AsyncGenerator[Any, Any]]:
    if job_id is None:
        job_id = str(uuid4())

    stream_key = compose_key(job_id)
    stream = redis_stream_reader(stream_key)

    # TODO: add a wrapper for the generator fn function to stream the data
    job = queue.enqueue(
        fn,
        *job_args,
        **job_kwargs,
        job_id=job_id,
    )

    return job, stream


def wait_for_job(
    job: Job, timeout: float = MAX_JOB_DURATION, poll_interval: float = 1
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
        job.refresh()

        if job.is_finished:
            return job.result
        elif job.is_failed:
            raise job.exc_info

        time.sleep(poll_interval)

    raise TimeoutError(f"Job {job.id} did not complete within {timeout} seconds")
