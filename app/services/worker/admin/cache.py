import time
from dataclasses import asdict
from datetime import timedelta

from loguru import logger

from app.config.settings import settings
from app.constants import CACHE_CLEANUP_TIMEOUT, CACHE_RECLAIM_MAX_ATTEMPTS
from app.context import cid_var
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage.cache import (
    cleanup_lock,
    reclaim_retired_roots,
    stamp_retired_roots,
)
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch
from app.job import JobFn


# The cleanup jobs wait for other jobs, so they must not wait for each other
CLEANUP_JOB_FUNC_NAMES = frozenset({JobFn.CLEAR_CACHE.value, JobFn.RECLAIM_RETIRED_CACHE.value})


def _stamp_retired_roots(kind: CacheKind, previous_epoch: str | None) -> None:
    stamp_retired_roots(kind, previous_epoch, exclude_func_names=CLEANUP_JOB_FUNC_NAMES)


def _schedule_reclaim(kind: CacheKind, attempt: int) -> None:
    get_queue(JobQueue.MEDIUM).enqueue_in(
        timedelta(seconds=settings.CACHE_RECLAIM_POLL_SECONDS),
        JobFn.RECLAIM_RETIRED_CACHE,
        kind.value,
        attempt,
        job_timeout=CACHE_CLEANUP_TIMEOUT,
        meta={"cid": cid_var.get()},
    )


def clear_cache(kind: CacheKind) -> dict:
    """Start a new epoch of the cache and delete the old one, once nothing can be using it."""
    with cleanup_lock(kind) as acquired:
        if not acquired:
            logger.info(f"Another {kind.value} cache cleanup is running, nothing to do")
            return {"status": "already_running"}

        previous = rotate_epoch(kind)
        logger.info(f"Started a new {kind.value} cache epoch, the previous one was {previous}")

        # Jobs that started a moment ago may not have seen the new epoch yet
        time.sleep(settings.CACHE_EPOCH_SETTLE_SECONDS)

        _stamp_retired_roots(kind, previous)
        result = reclaim_retired_roots(kind)

    if result.pending:
        _schedule_reclaim(kind, attempt=1)

    return {"status": "ok", **asdict(result)}


def reclaim_retired_cache(kind: CacheKind, attempt: int) -> dict:
    """Delete the retired epochs of the cache that jobs have stopped using."""
    with cleanup_lock(kind) as acquired:
        if not acquired:
            # Whoever holds the lock schedules another check if one is needed
            logger.info(f"Another {kind.value} cache cleanup is running, nothing to do")
            return {"status": "already_running"}

        _stamp_retired_roots(kind, None)
        result = reclaim_retired_roots(kind)

    if result.pending:
        if attempt >= CACHE_RECLAIM_MAX_ATTEMPTS:
            logger.error(
                f"{result.pending} retired {kind.value} cache epochs are still there after "
                f"{attempt} checks, run the cache cleanup again to retry"
            )
        else:
            _schedule_reclaim(kind, attempt + 1)

    return {"status": "ok", **asdict(result)}
