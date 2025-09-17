from enum import StrEnum
from typing import Callable, Dict
from rq import Queue
from rq import get_current_job

from app.infrastructure.redis import redis_client
from app.utils.streaming import compose_key


class JobQueue(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_queues: Dict[JobQueue, Queue] = {
    queue_name: Queue(queue_name.value, connection=redis_client) for queue_name in JobQueue
}


def queue_factory(job_queue: JobQueue) -> Callable[[], Queue]:
    def get_queue() -> Queue:
        return _queues[job_queue]

    return get_queue


def get_queue(job_queue: JobQueue) -> Queue:
    """Get a queue instance by name."""
    return _queues[job_queue]


def get_job_stream_key() -> str:
    """Get stream key for current job.
    Can be called only from a worker.
    """
    job = get_current_job()

    if job is None:
        raise ValueError("No job found")

    return compose_key(job.id)


def get_current_job_id() -> str:
    """Get current job id.
    Can be called only from a worker.
    """
    job = get_current_job()

    if job is None:
        raise ValueError("No job available")

    return job.id
