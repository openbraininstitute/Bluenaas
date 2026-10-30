"""The LFP reports' summaries in the cache, read by the API and built by the jobs.

A summary is built the first time it is asked for and kept in the cache until the cache is cleared.
Its directory holds the summary and its index once `.ready` is there, or `.no-summary` with the
reason it never will. A new format version is a new directory, so summaries of the previous one are
built again.

Nothing here imports the worker's dependencies: the API runs the failure callback of a build whose
worker died, when it cleans up the registry of started jobs.
"""

import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from loguru import logger
from rq import Callback, Retry
from rq.exceptions import DuplicateJobError
from rq.job import Job, JobStatus

from app.config.settings import settings
from app.constants import DIR_LOCK_FILE_NAME, MAX_JOB_TIMEOUT, READY_MARKER_FILE_NAME
from app.context import cid_var
from app.domains.simulation_result.lfp_summary import NoSummaryReason
from app.infrastructure.redis import redis_client
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage import uuid_subpath
from app.infrastructure.storage.epoch import CacheKind, epoch_dir_name
from app.job import JobFn

FORMAT_VERSION = 1

SUMMARY_FILE_NAME = "summary.h5"
INDEX_FILE_NAME = "index.json"
SUMMARY_INFO_FILE_NAME = "summary.json"
NO_SUMMARY_FILE_NAME = ".no-summary"

# Reports up to this size are summarised on `low`, in one worker's share of a shared task
SMALL_REPORT_BYTES = 2**30
# No summary is made of a larger report: at about 0.5 GB/s, a build would near the job timeout
MAX_REPORT_BYTES = 1_000 * 2**30

BUILD_QUEUES = (JobQueue.LOW, JobQueue.CPU4_MEM16)

# A build that failed after its retry is not tried again for this long
FAILED_BUILD_TTL = 24 * 60 * 60

# How long a request that queues a build keeps the others from queueing the same one, at most
ENQUEUE_GUARD_SECONDS = 10

LIVE_STATUSES = frozenset(
    {JobStatus.QUEUED, JobStatus.SCHEDULED, JobStatus.STARTED, JobStatus.DEFERRED}
)


@dataclass(frozen=True)
class SummaryInfo:
    size: int
    sha256: str
    # The queue of the build that made it
    queue: str


def summary_dir(epoch: str, asset_id: UUID) -> Path:
    """The report's directory in the given epoch of the cache. Not created."""
    return (
        settings.STORAGE_PATH
        / CacheKind.LFP_SUMMARY.value
        / epoch_dir_name(epoch)
        / f"v{FORMAT_VERSION}"
        / uuid_subpath(asset_id)
    )


def read_summary_info(directory: Path) -> SummaryInfo | None:
    """The summary's info, None if it is not ready."""
    if not (directory / READY_MARKER_FILE_NAME).exists():
        return None
    try:
        return SummaryInfo(**json.loads((directory / SUMMARY_INFO_FILE_NAME).read_text()))
    except (OSError, ValueError, TypeError):
        logger.warning(f"The LFP summary in {directory} is ready but its info can't be read")
        return None


def read_no_summary_reason(directory: Path) -> NoSummaryReason | None:
    try:
        return NoSummaryReason(json.loads((directory / NO_SUMMARY_FILE_NAME).read_text())["reason"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning(f"The no-summary marker in {directory} can't be read")
        return NoSummaryReason.UNREADABLE


def write_atomically(path: Path, content: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def write_summary_info(directory: Path, info: SummaryInfo) -> None:
    write_atomically(directory / SUMMARY_INFO_FILE_NAME, json.dumps(asdict(info)))


def write_no_summary(directory: Path, reason: NoSummaryReason, details: str) -> None:
    write_atomically(
        directory / NO_SUMMARY_FILE_NAME, json.dumps({"reason": reason.value, "details": details})
    )


def build_job_id(epoch: str, asset_id: UUID, queue: JobQueue) -> str:
    return f"lfp-summary-{epoch}-v{FORMAT_VERSION}-{asset_id}-{queue.value}"


def build_queue(report_bytes: int) -> JobQueue:
    return JobQueue.LOW if report_bytes <= SMALL_REPORT_BYTES else JobQueue.CPU4_MEM16


def remove_build_leftovers(job: Job, connection, exc_type, exc_value, traceback) -> None:
    """The failure callback of a build: frees the summary's lock and removes the partial files.

    It runs as the morphology pack's does, in the worker's work horse or in whichever process cleans
    up the started jobs after the worker died.
    """
    try:
        directory = summary_dir(job.kwargs["epoch"], UUID(str(job.kwargs["asset_id"])))
        for path in [directory / DIR_LOCK_FILE_NAME, *directory.glob("*.tmp")]:
            with suppress(FileNotFoundError):
                os.unlink(path)
    except Exception:
        # Raised, it would stop the cleanup of the started jobs before the retry is queued
        logger.exception(f"Could not remove what the LFP summary build {job.id} left")

    logger.error(f"LFP summary build {job.id} failed with {exc_type.__name__}: {exc_value}")


def enqueue_build(
    queue: JobQueue,
    *,
    epoch: str,
    asset_id: UUID,
    url: str,
    size: int,
) -> Job | None:
    """Queue the build of the report at `url`, a presigned URL that is read by range, unless a job
    of the same id is already queued or running. Returns the job queued, None if there was one
    already.
    """
    rq_queue = get_queue(queue)
    job_id = build_job_id(epoch, asset_id, queue)

    # Else a request could delete the job another one has just queued in place of a finished one
    guard = f"lfp-summary:enqueue:{job_id}"
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
            JobFn.RUN_LFP_SUMMARY,
            job_id=job_id,
            unique=True,
            kwargs={
                "asset_id": asset_id,
                "epoch": epoch,
                "queue": queue.value,
                "url": url,
                "size": size,
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
