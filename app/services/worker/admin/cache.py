from dataclasses import asdict

from loguru import logger

from app.config.settings import settings
from app.constants import CACHE_RECLAIM_MAX_ATTEMPTS
from app.infrastructure.redis import redis_client
from app.infrastructure.storage.cache import (
    cleanup_lock,
    enqueue_reclaim,
    epoch_dir,
    has_unfinished_cleanup,
    reclaim_retired_roots,
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

    enqueue_reclaim(
        kind,
        attempt=attempt + 1,
        previous_epoch=previous_epoch,
        delay_seconds=settings.CACHE_RECLAIM_POLL_SECONDS,
    )


def _reclaim_once(
    kind: CacheKind, previous_epoch: str | None, mark: bool
) -> tuple[dict, str | None] | None:
    """Returns the result of the reclaim and the previous epoch if it is not marked as trusted
    yet, or None if another cleanup holds the lock."""
    with cleanup_lock(kind) as acquired:
        if not acquired:
            return None

        if not mark:
            return asdict(reclaim_retired_roots(kind)), None

        markers = stamp_retired_roots(
            kind, previous_epoch, exclude_func_names=CLEANUP_JOB_FUNC_NAMES
        )
        unmarked = None
        if previous_epoch:
            marker = markers.get(epoch_dir(kind, previous_epoch))
            if marker is None or not marker.trusted:
                unmarked = previous_epoch
        return asdict(reclaim_retired_roots(kind, markers)), unmarked


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
        outcome = _reclaim_once(kind, previous_epoch, mark)
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

    if outcome is None:
        logger.info(f"Another {kind.value} cache cleanup is running, checking again later")
        if follow_up:
            _schedule_again(kind, attempt, previous_epoch)
        return {"status": "already_running"}

    result, unmarked = outcome
    if result["pending"] and follow_up:
        # Once the epoch the cleanup retired has its marker, the next checks do not need to know
        # which one it was. Passed on, it would be created again after it is deleted.
        _schedule_again(kind, attempt, unmarked)

    return {"status": "ok", **result}


def _startup_check_key(kind: CacheKind) -> str:
    return f"cache:reclaim-on-worker-start:{kind.value}"


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
        key = _startup_check_key(kind)
        if not _try_set(key):
            continue
        try:
            if has_unfinished_cleanup(kind):
                enqueue_reclaim(kind, follow_up=False, mark=False)
                logger.info(f"Queued a check of the retired {kind.value} cache epochs")
        except Exception:
            logger.exception(f"Could not queue a check of the retired {kind.value} cache epochs")
            # Leaves it to the next worker that starts
            _try_delete(key)


def _try_set(key: str) -> bool:
    try:
        return bool(redis_client.set(key, "1", nx=True, ex=settings.CACHE_RECLAIM_POLL_SECONDS))
    except Exception:
        logger.exception(f"Could not set {key}")
        return False


def _try_delete(key: str) -> None:
    try:
        redis_client.delete(key)
    except Exception:
        logger.exception(f"Could not delete {key}")
