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


def _schedule_reclaim(
    kind: CacheKind, *, attempt: int, previous_epoch: str | None, delay_seconds: int
) -> None:
    get_queue(JobQueue.MEDIUM).enqueue_in(
        timedelta(seconds=delay_seconds),
        JobFn.RECLAIM_RETIRED_CACHE,
        kind.value,
        attempt,
        previous_epoch,
        job_timeout=CACHE_CLEANUP_TIMEOUT,
        meta={"cid": cid_var.get()},
    )


def clear_cache(kind: CacheKind) -> dict:
    """Start a new epoch of the cache, so that no new job uses the old one, and schedule the
    deletion of the old one.

    This does not wait for anything, so it takes effect even if another cleanup is running.
    """
    previous = rotate_epoch(kind)
    logger.info(f"Started a new {kind.value} cache epoch, the previous one was {previous}")

    # Jobs that started a moment ago may not have seen the new epoch yet, so the jobs that might
    # use the previous one are listed only after a pause. The scheduled job does not hold a worker
    # during the pause.
    _schedule_reclaim(
        kind,
        attempt=1,
        previous_epoch=previous,
        delay_seconds=settings.CACHE_EPOCH_SETTLE_SECONDS,
    )
    return {"status": "ok", "previous_epoch": previous}


def _schedule_again(kind: CacheKind, attempt: int, previous_epoch: str | None) -> None:
    if attempt >= CACHE_RECLAIM_MAX_ATTEMPTS:
        logger.error(
            f"Retired {kind.value} cache epochs are still there after {attempt} checks, "
            "run the cache cleanup again to retry"
        )
        return

    _schedule_reclaim(
        kind,
        attempt=attempt + 1,
        previous_epoch=previous_epoch,
        delay_seconds=settings.CACHE_RECLAIM_POLL_SECONDS,
    )


def _reclaim_once(kind: CacheKind, previous_epoch: str | None) -> dict | None:
    """Returns the result of the reclaim, or None if another cleanup holds the lock."""
    with cleanup_lock(kind) as acquired:
        if not acquired:
            return None

        stamp_retired_roots(kind, previous_epoch, exclude_func_names=CLEANUP_JOB_FUNC_NAMES)
        return asdict(reclaim_retired_roots(kind))


def reclaim_retired_cache(kind: CacheKind, attempt: int, previous_epoch: str | None = None) -> dict:
    """Delete the retired epochs of the cache that jobs have stopped using.

    `previous_epoch` is the epoch that the cleanup that scheduled this job retired. Checks that
    have to be repeated, because epochs are still in use or because the lock was taken, are
    scheduled again, also when this one fails.
    """
    try:
        result = _reclaim_once(kind, previous_epoch)
    except Exception:
        logger.exception(f"Reclaiming the retired {kind.value} cache epochs failed")
        _schedule_again(kind, attempt, previous_epoch)
        raise

    if result is None:
        logger.info(f"Another {kind.value} cache cleanup is running, checking again later")
        _schedule_again(kind, attempt, previous_epoch)
        return {"status": "already_running"}

    if result["pending"]:
        _schedule_again(kind, attempt, previous_epoch)

    return {"status": "ok", **result}
