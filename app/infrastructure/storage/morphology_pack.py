"""The circuits' morphology packs in the cache, read by the API and built by the jobs.

A pack is built the first time it is asked for and kept in the cache until the cache is cleared.
Its directory holds the pack once `.ready` is there, or `.no-pack` with the reason it never will.

Nothing here imports the worker's dependencies: the API runs the failure callback of a build whose
worker died, when it cleans up the registry of started jobs.
"""

import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from entitysdk.common import ProjectContext
from loguru import logger
from rq import Callback, Retry
from rq.exceptions import DuplicateJobError
from rq.job import Job, JobStatus
from rq.registry import StartedJobRegistry
from rq.timeouts import TimerDeathPenalty

from app.config.settings import settings
from app.constants import DIR_LOCK_FILE_NAME, MAX_JOB_TIMEOUT, READY_MARKER_FILE_NAME
from app.context import cid_var
from app.domains.circuit.morphology_pack import NoPackReason
from app.infrastructure.redis import redis_client
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage import uuid_subpath
from app.infrastructure.storage.epoch import CacheKind, epoch_dir_name
from app.job import JobFn

PACK_FILE_NAME = "pack.mpack"
PACK_INFO_FILE_NAME = "pack.json"
NO_PACK_FILE_NAME = ".no-pack"

# Circuits up to this many neurons are built on `low`, in one worker's share of a shared task
SMALL_BUILD_MAX_NEURONS = 2_000
# No pack is built for more neurons: the whole FlyWire brain is the largest circuit that fits
MAX_NEURONS = 160_000

BUILD_QUEUES = (JobQueue.LOW, JobQueue.CPU4_MEM16)

# A build that failed after its retry is not tried again for this long
FAILED_BUILD_TTL = 24 * 60 * 60

# The registries of started jobs are cleaned up at most this often
CLEANUP_INTERVAL_SECONDS = 30

# How long a request that queues a build keeps the others from queueing the same one, at most
ENQUEUE_GUARD_SECONDS = 10

LIVE_STATUSES = frozenset(
    {JobStatus.QUEUED, JobStatus.SCHEDULED, JobStatus.STARTED, JobStatus.DEFERRED}
)


@dataclass(frozen=True)
class PackInfo:
    size: int
    sha256: str
    # The queue of the build that made it
    queue: str


def pack_dir(epoch: str, circuit_id: UUID) -> Path:
    """The circuit's directory in the given epoch of the cache. Not created."""
    return (
        settings.STORAGE_PATH
        / CacheKind.MORPHOLOGY_PACK.value
        / epoch_dir_name(epoch)
        / uuid_subpath(circuit_id)
    )


def read_pack_info(directory: Path) -> PackInfo | None:
    """The pack's info, None if it is not ready."""
    if not (directory / READY_MARKER_FILE_NAME).exists():
        return None
    try:
        return PackInfo(**json.loads((directory / PACK_INFO_FILE_NAME).read_text()))
    except (OSError, ValueError, TypeError):
        logger.warning(f"The morphology pack in {directory} is ready but its info can't be read")
        return None


def read_no_pack_reason(directory: Path) -> NoPackReason | None:
    try:
        return NoPackReason(json.loads((directory / NO_PACK_FILE_NAME).read_text())["reason"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning(f"The no-pack marker in {directory} can't be read")
        return NoPackReason.NO_MORPHOLOGIES


def _write_atomically(path: Path, content: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def write_pack_info(directory: Path, info: PackInfo) -> None:
    _write_atomically(directory / PACK_INFO_FILE_NAME, json.dumps(asdict(info)))


def write_no_pack(directory: Path, reason: NoPackReason, details: str) -> None:
    _write_atomically(
        directory / NO_PACK_FILE_NAME, json.dumps({"reason": reason.value, "details": details})
    )


def build_job_id(epoch: str, circuit_id: UUID, queue: JobQueue) -> str:
    return f"morphology-pack-{epoch}-{circuit_id}-{queue.value}"


def remove_build_leftovers(job: Job, connection, exc_type, exc_value, traceback) -> None:
    """The failure callback of a build: frees the pack's lock and removes the partial files.

    It runs in the worker's work horse after an exception or the timeout, and in whichever process
    cleans up the started jobs after the worker died (the API among them). The build holds the lock
    no more in either case. Deleting the lock file is how filelock itself releases it, and the next
    build locks a new file, whatever a dead host's lease on the old one still holds.
    """
    try:
        directory = pack_dir(job.kwargs["epoch"], UUID(str(job.kwargs["circuit_id"])))
        for path in [directory / DIR_LOCK_FILE_NAME, *directory.glob("*.tmp")]:
            with suppress(FileNotFoundError):
                os.unlink(path)
    except Exception:
        # Raised, it would stop the cleanup of the started jobs before the retry is queued
        logger.exception(f"Could not remove what the morphology pack build {job.id} left")

    logger.error(f"Morphology pack build {job.id} failed with {exc_type.__name__}: {exc_value}")


def enqueue_build(
    queue: JobQueue,
    *,
    epoch: str,
    circuit_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> Job | None:
    """Queue the build, unless a job of the same id is already queued or running. Returns the job
    queued, None if there was one already.
    """
    rq_queue = get_queue(queue)
    job_id = build_job_id(epoch, circuit_id, queue)

    # Else a request could delete the job another one has just queued in place of a finished one
    guard = f"morphology-pack:enqueue:{job_id}"
    if not redis_client.set(guard, 1, nx=True, ex=ENQUEUE_GUARD_SECONDS):
        return None

    try:
        previous = rq_queue.fetch_job(job_id)
        if previous is not None:
            if previous.get_status(refresh=False) in LIVE_STATUSES:
                return None
            # Fields a new job does not set would be kept from the previous one
            previous.delete()

        return rq_queue.enqueue(
            JobFn.RUN_MORPHOLOGY_PACK,
            job_id=job_id,
            unique=True,
            kwargs={
                "circuit_id": circuit_id,
                "epoch": epoch,
                "queue": queue.value,
                "access_token": access_token,
                "project_context": project_context,
            },
            job_timeout=MAX_JOB_TIMEOUT,
            retry=Retry(max=1),
            on_failure=Callback(remove_build_leftovers),
            failure_ttl=FAILED_BUILD_TTL,
            meta={"cid": cid_var.get()},
        )
    except DuplicateJobError:
        return None
    finally:
        redis_client.delete(guard)


def clean_up_abandoned_builds() -> None:
    """Fail or retry the builds whose worker died, as RQ does for a queue it has workers on.

    A queue served by batch workers may have none left to do it. At most one cleanup of a queue
    every `CLEANUP_INTERVAL_SECONDS`: two at once could both run a dead build's failure callback
    and both retry it.
    """
    for queue in BUILD_QUEUES:
        if not redis_client.set(
            f"morphology-pack:cleanup:{queue.value}", 1, nx=True, ex=CLEANUP_INTERVAL_SECONDS
        ):
            continue
        # The default death penalty sets a signal handler, which only the main thread may do
        registry = StartedJobRegistry(queue=get_queue(queue), death_penalty_class=TimerDeathPenalty)
        try:
            registry.cleanup()
        except Exception:
            # The failure callback of another kind of job on the queue raised. Its worker's own
            # maintenance cleans the registry up then.
            logger.exception(f"Could not clean up the started jobs of {queue.value}")
