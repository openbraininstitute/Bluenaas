from dataclasses import asdict

from loguru import logger

from app.config.settings import settings
from app.constants import CACHE_CLEANUP_TIMEOUT, CACHE_RECLAIM_MAX_ATTEMPTS
from app.context import cid_var
from app.infrastructure.redis import redis_client
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage.cache import (
    cleanup_lock,
    has_unfinished_cleanup,
    reclaim_retired_roots,
    schedule_reclaim,
    stamp_retired_roots,
)
from app.infrastructure.storage.epoch import CacheKind
from app.job import JobFn


# The cleanup jobs wait for other jobs, so they must not wait for each other
CLEANUP_JOB_FUNC_NAMES = frozenset({JobFn.RECLAIM_RETIRED_CACHE.value})


def _schedule_again(kind: CacheKind, attempt: int, previous_epoch: str | None) -> None:
    if attempt >= CACHE_RECLAIM_MAX_ATTEMPTS:
        logger.error(
            f"Retired {kind.value} cache epochs are still there after {attempt} checks, "
            "run the cache cleanup again to retry"
        )
        return

    schedule_reclaim(
        kind,
        attempt=attempt + 1,
        previous_epoch=previous_epoch,
        delay_seconds=settings.CACHE_RECLAIM_POLL_SECONDS,
    )


def _reclaim_once(kind: CacheKind, previous_epoch: str | None, mark: bool) -> dict | None:
    """Returns the result of the reclaim, or None if another cleanup holds the lock."""
    with cleanup_lock(kind) as acquired:
        if not acquired:
            return None

        markers = (
            stamp_retired_roots(kind, previous_epoch, exclude_func_names=CLEANUP_JOB_FUNC_NAMES)
            if mark
            else None
        )
        return asdict(reclaim_retired_roots(kind, markers))


def reclaim_retired_cache(
    kind: CacheKind,
    attempt: int,
    previous_epoch: str | None = None,
    follow_up: bool = True,
    mark: bool = True,
) -> dict:
    """Delete the retired epochs of the cache that jobs have stopped using.

    `previous_epoch` is the epoch that the cleanup that scheduled this job retired. Checks that
    have to be repeated, because epochs are still in use or because the lock was taken, are
    scheduled again, also when this one fails, unless `follow_up` is off. Without `mark`, only
    the retired epochs that are marked already are deleted.
    """
    try:
        result = _reclaim_once(kind, previous_epoch, mark)
    except Exception:
        logger.exception(f"Reclaiming the retired {kind.value} cache epochs failed")
        if follow_up:
            try:
                _schedule_again(kind, attempt, previous_epoch)
            except Exception:
                logger.exception(
                    f"Could not schedule the next check of the retired {kind.value} cache "
                    "epochs, they are left until the next cleanup or worker start"
                )
        raise

    if result is None:
        logger.info(f"Another {kind.value} cache cleanup is running, checking again later")
        if follow_up:
            _schedule_again(kind, attempt, previous_epoch)
        return {"status": "already_running"}

    if result["pending"] and follow_up:
        # The epoch the cleanup retired has its marker by now, the next checks do not need to
        # know which one it was
        _schedule_again(kind, attempt, None)

    return {"status": "ok", **result}


def _kick_key(kind: CacheKind) -> str:
    return f"cache:reclaim-kick:{kind.value}"


def start_pending_reclaims() -> None:
    """Queue a single check of the caches with a cleanup that was cut short.

    The checks a cleanup schedules stop after a while, or when one of them cannot schedule the
    next. Workers call this when they start, so that the epochs such a cleanup marked are deleted
    eventually. Only one worker of the ones starting together does it.

    The check does not mark anything: before the first cleanup, every directory of the layout
    from before the epochs looks retired, and old workers may still be using them during a
    deploy. Epochs that a cleanup retired but never marked, e.g. because the API could not
    schedule the first check, are left for the next cleanup, which deletes them by age.
    """
    for kind in CacheKind:
        try:
            if not redis_client.set(
                _kick_key(kind), "1", nx=True, ex=settings.CACHE_RECLAIM_POLL_SECONDS
            ):
                continue
            if not has_unfinished_cleanup(kind):
                continue

            # Not scheduled: in burst mode a scheduled job waits for the next worker to start
            get_queue(JobQueue.MEDIUM).enqueue(
                JobFn.RECLAIM_RETIRED_CACHE,
                kind.value,
                1,
                follow_up=False,
                mark=False,
                job_timeout=CACHE_CLEANUP_TIMEOUT,
                meta={"cid": cid_var.get()},
            )
            logger.info(f"Queued a check of the retired {kind.value} cache epochs")
        except Exception:
            logger.exception(f"Could not queue a check of the retired {kind.value} cache epochs")
