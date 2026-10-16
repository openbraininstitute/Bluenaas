"""Retiring and reclaiming cache epochs (see `epoch.py` for how epochs work).

A cache epoch is *retired* when it is no longer the current one. Jobs that start after that use the
new epoch, so only jobs that were already running can still be using the retired one. Such an epoch
is deleted (*reclaimed*) once those jobs have finished, or at the latest after
`CACHE_RETIRED_MAX_AGE`, which is longer than a job can run.

The jobs that might use a retired epoch are written into a marker file inside it when it is first
seen as retired, so that a cleanup that is interrupted, or run by another worker, can pick up where
the last one stopped. Directories of a cache kind that are not epochs (the layout from before the
epochs) are retired epochs too.

Nothing here relies on file locks or on a rename that happens under a reader, so it behaves the
same on a local disk and on a network filesystem.
"""

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from loguru import logger
from redis.exceptions import LockError

from app.config.settings import settings
from app.constants import CACHE_CLEANUP_TIMEOUT, RETIRED_MARKER_FILE_NAME, STORAGE_TRASH_DIR_NAME
from app.infrastructure.redis import redis_client
from app.infrastructure.rq import get_picked_up_job_ids, get_unfinished_job_ids
from app.infrastructure.storage import rm_dir_parallel
from app.infrastructure.storage.epoch import (
    CacheKind,
    epoch_dir_name,
    get_epoch,
    is_epoch_dir_name,
)
from app.job import JobFn

# The cleanup jobs wait for other jobs, so they must not wait for each other
CLEANUP_JOB_FUNC_NAMES = frozenset({JobFn.CLEAR_CACHE.value, JobFn.RECLAIM_RETIRED_CACHE.value})


@dataclass(frozen=True)
class RetiredMarker:
    retired_at: float
    blocking_job_ids: tuple[str, ...]
    # Whether `blocking_job_ids` is known to include every job that uses the epoch. If not, the
    # epoch can only be deleted by age.
    trusted: bool = True


@dataclass
class ReclaimResult:
    reclaimed: int = 0
    # Retired epochs that are still there, because jobs may still use them or removing them failed
    pending: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"reclaimed": self.reclaimed, "pending": self.pending}


def _kind_dir(kind: CacheKind) -> Path:
    return settings.STORAGE_PATH / kind.value


def _trash_dir(kind: CacheKind) -> Path:
    return settings.STORAGE_PATH / STORAGE_TRASH_DIR_NAME / kind.value


@contextmanager
def cleanup_lock(kind: CacheKind) -> Iterator[bool]:
    """Only one cleanup of a cache kind at a time. Yields whether this one got the lock."""
    lock = redis_client.lock(
        f"cache:cleanup-lock:{kind.value}", timeout=CACHE_CLEANUP_TIMEOUT, blocking=False
    )
    acquired = bool(lock.acquire())
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except LockError:
                logger.warning(f"The {kind.value} cache cleanup lock expired before the release")


def retired_roots(kind: CacheKind) -> list[Path]:
    """The directories of the cache kind that are not its current epoch."""
    kind_dir = _kind_dir(kind)
    if not kind_dir.is_dir():
        return []

    current = get_epoch(kind)
    current_name = epoch_dir_name(current) if current else None

    return [
        p
        for p in kind_dir.iterdir()
        if p.is_dir() and not p.is_symlink() and p.name != current_name
    ]


def _read_marker(root: Path) -> RetiredMarker | None:
    try:
        data = json.loads((root / RETIRED_MARKER_FILE_NAME).read_text())
        return RetiredMarker(
            retired_at=float(data["retired_at"]),
            blocking_job_ids=tuple(data["blocking_job_ids"]),
            trusted=bool(data.get("trusted", False)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_marker(root: Path, marker: RetiredMarker) -> None:
    content = json.dumps(
        {
            "retired_at": marker.retired_at,
            "blocking_job_ids": list(marker.blocking_job_ids),
            "trusted": marker.trusted,
        }
    )
    tmp = root / f"{RETIRED_MARKER_FILE_NAME}.{uuid4().hex}.tmp"
    tmp.write_text(content)
    os.replace(tmp, root / RETIRED_MARKER_FILE_NAME)


def stamp_retired_roots(kind: CacheKind, previous_epoch: str | None = None) -> None:
    """Write the marker into the retired epochs that do not have one yet.

    The jobs recorded are the ones running now. For the epoch that was retired by the cleanup that
    calls this (`previous_epoch`), and for epochs from before there were epochs, they include every
    job that could be using it: a job takes its epoch only once it is running.

    That does not hold for any other epoch directory that is not marked yet. It was retired by a
    cleanup that stopped before marking it, or Redis lost its data, which also loses the record of
    the jobs that are running, so the jobs listed now may be missing some that use that epoch.
    Such an epoch is marked as not trusted and is deleted only when it is old enough.
    """
    unmarked = [root for root in retired_roots(kind) if _read_marker(root) is None]
    if not unmarked:
        return

    blocking = tuple(sorted(get_picked_up_job_ids(exclude_func_names=CLEANUP_JOB_FUNC_NAMES)))
    retired_at = time.time()
    known_epoch = epoch_dir_name(previous_epoch) if previous_epoch else None

    for root in unmarked:
        trusted = not is_epoch_dir_name(root.name) or root.name == known_epoch
        try:
            _write_marker(root, RetiredMarker(retired_at, blocking, trusted))
        except OSError as ex:
            logger.warning(f"Could not mark {root} as retired: {ex}")


def _is_reclaimable(marker: RetiredMarker, now: float) -> bool:
    if now - marker.retired_at >= settings.CACHE_RETIRED_MAX_AGE:
        return True
    if not marker.trusted:
        return False
    return not get_unfinished_job_ids(marker.blocking_job_ids)


def _purge_trash(kind: CacheKind) -> None:
    """Delete what an interrupted cleanup left behind."""
    trash = _trash_dir(kind)
    if not trash.is_dir():
        return
    for leftover in trash.iterdir():
        rm_dir_parallel(leftover, workers=settings.CACHE_CLEANUP_WORKERS)


def reclaim_retired_roots(kind: CacheKind) -> ReclaimResult:
    """Delete the retired epochs that no running job can be using any more."""
    result = ReclaimResult()
    _purge_trash(kind)

    now = time.time()
    for root in retired_roots(kind):
        marker = _read_marker(root)
        if marker is None or not _is_reclaimable(marker, now):
            logger.info(f"{root} is still in use or not marked yet, keeping it for now")
            result.pending += 1
            continue

        trashed = _trash_dir(kind) / uuid4().hex
        try:
            trashed.parent.mkdir(parents=True, exist_ok=True)
            os.rename(root, trashed)
        except FileNotFoundError:
            continue
        except OSError as ex:
            logger.warning(f"Could not move {root} to the trash: {ex}")
            result.pending += 1
            continue

        logger.info(f"Deleting retired cache epoch {root}")
        rm_dir_parallel(trashed, workers=settings.CACHE_CLEANUP_WORKERS)
        result.reclaimed += 1

    return result
