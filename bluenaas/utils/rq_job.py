from typing import Any, AsyncGenerator, Callable
from uuid import uuid4
from rq.job import Job
from rq import Queue
from loguru import logger

from bluenaas.utils.streaming import compose_key
from bluenaas.infrastructure.redis.async_redis import redis_stream_reader


def dispatch(
    queue: Queue,
    fn: Callable[..., Any],
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
