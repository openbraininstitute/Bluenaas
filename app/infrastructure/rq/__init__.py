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
    CPU4_MEM16 = "4cpu-16gb"  # heavy jobs, a task of 4 CPUs and 16 GB each


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


def get_started_job_ids(*, exclude_func_names: Collection[str]) -> set[str]:
    """Ids of the started jobs that have not finished yet.

    Jobs that are not started yet are not included: a job takes its cache epochs only once it is
    in the started registry (see `LoggingWorker.prepare_job_execution`).
    """
    queues = {queue.name: queue for queue in Queue.all(connection=redis_client)}
    queues.update({queue.name: queue for queue in _queues.values()})

    job_ids: set[str] = set()
    for queue in queues.values():
        # Without the cleanup of the registry: it fails the abandoned jobs and runs their failure
        # callbacks, which is not for a cache cleanup to do. Abandoned jobs are left out instead.
        registry = queue.started_job_registry
        job_ids.update(
            set(registry.get_job_ids(cleanup=False)) - set(registry.get_expired_job_ids())
        )

    return {
        job.id for job in _unfinished_jobs(job_ids) if not _runs_function(job, exclude_func_names)
    }


def get_unfinished_job_ids(job_ids: Iterable[str]) -> set[str]:
    """The ids out of the given ones whose job still exists and has not finished.

    A job that does not exist any more (its record expired) has finished.
    """
    return {job.id for job in _unfinished_jobs(job_ids)}
