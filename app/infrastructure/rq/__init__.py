from enum import StrEnum
from typing import Callable, Collection, Dict, Iterable
from rq import Queue
from rq import get_current_job
from loguru import logger
from rq.job import Job, JobStatus

from app.infrastructure.redis import redis_client
from app.utils.streaming import compose_key


class JobQueue(StrEnum):
    # TODO Refactor names to be more descriptive
    HIGH = "high"  # single cpu hi-priority / realtime tasks
    MEDIUM = "medium"  # single cpu low-priority tasks
    LOW = "low"  # multi cpu tasks, e.g. circuit simulation


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


def _runs_function(job: Job, func_names: Collection[str]) -> bool:
    try:
        return job.func_name in func_names
    except Exception as ex:
        # The record cannot be read, e.g. it was written by another version of the code
        logger.warning(f"Could not read the function of job {job.id}: {ex}")
        return False


_FINISHED_STATUSES = frozenset(
    {JobStatus.FINISHED, JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED}
)


def _unfinished_jobs(job_ids: Iterable[str]) -> list[Job]:
    jobs = Job.fetch_many(job_ids, connection=redis_client)
    return [
        job
        for job in jobs
        if job is not None and job.get_status(refresh=False) not in _FINISHED_STATUSES
    ]


def get_picked_up_job_ids(*, exclude_func_names: Collection[str]) -> set[str]:
    """Ids of the jobs that a worker has taken from a queue and that have not finished yet.

    A job counts from the moment it leaves the queue (the intermediate queue), not only once it
    is in the started registry. Queued, deferred and scheduled jobs are not included, they have
    not started to use anything yet.
    """
    queues = {queue.name: queue for queue in Queue.all(connection=redis_client)}
    queues.update({queue.name: queue for queue in _queues.values()})

    job_ids: set[str] = set()
    for queue in queues.values():
        job_ids.update(queue.started_job_registry.get_job_ids())
        job_ids.update(queue.intermediate_queue.get_job_ids())

    return {
        job.id for job in _unfinished_jobs(job_ids) if not _runs_function(job, exclude_func_names)
    }


def get_unfinished_job_ids(job_ids: Iterable[str]) -> set[str]:
    """The ids out of the given ones whose job still exists and has not finished.

    A job that does not exist any more (its record expired) has finished.
    """
    return {job.id for job in _unfinished_jobs(job_ids)}
