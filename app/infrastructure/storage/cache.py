"""Retiring and reclaiming cache epochs (see `epoch.py` for how epochs work).

A cache epoch is *retired* when it is no longer the current one. Jobs that start after that use the
new epoch, so only jobs that were already running can still be using the retired one. Such an epoch
is deleted (*reclaimed*) once those jobs have finished, or at the latest after
`CACHE_RETIRED_MAX_AGE`, which is longer than a job can run.

The jobs that might use a retired epoch are written into a marker file inside it when it is first
seen as retired, so that a cleanup that is interrupted, or run by another worker, can pick up where
the last one stopped. Directories of a cache kind that are not epochs (the layout from before the
epochs), and the directories where a cache kind was kept before, are retired epochs too.

Nothing here relies on file locks or on a rename that happens under a reader, so it behaves the
same on a local disk and on a network filesystem.
"""

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Collection, Iterator, Mapping
from uuid import uuid4

from loguru import logger
from redis.exceptions import LockError
from redis.lock import Lock
from rq.job import Job

from app.config.settings import settings
from app.constants import (
    CACHE_CLEANUP_LOCK_TTL,
    CACHE_CLEANUP_TIMEOUT,
    RETIRED_MARKER_FILE_NAME,
    STORAGE_TRASH_DIR_NAME,
)
from app.context import cid_var
from app.infrastructure.redis import redis_client
from app.infrastructure.rq import (
    JobQueue,
    get_queue,
    get_started_job_ids,
    get_unfinished_job_ids,
)
from app.infrastructure.storage import rm_dir_parallel
from app.infrastructure.storage.epoch import CacheKind, epoch_dir_name, get_epoch
from app.job import JobFn

# Directories under STORAGE_PATH where a cache kind was kept before
_FORMER_ROOTS: dict[CacheKind, tuple[str, ...]] = {
    # The ion channel builds, before they became one of the task config runs
    CacheKind.TASK_CONFIG: ("ion-channel",),
    CacheKind.COMPILATION: ("compilation-cache",),
}


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


def _kind_dir(kind: CacheKind) -> Path:
    return settings.STORAGE_PATH / kind.value


def _trash_dir(kind: CacheKind) -> Path:
    return settings.STORAGE_PATH / STORAGE_TRASH_DIR_NAME / kind.value


def epoch_dir(kind: CacheKind, epoch: str) -> Path:
    return _kind_dir(kind) / epoch_dir_name(epoch)


def _renew_lock(lock: Lock, kind: CacheKind, stop: threading.Event) -> None:
    while not stop.wait(CACHE_CLEANUP_LOCK_TTL / 3):
        try:
            lock.extend(CACHE_CLEANUP_LOCK_TTL, replace_ttl=True)
        except LockError:
            logger.warning(f"Lost the {kind.value} cache cleanup lock")
            return
        except Exception:
            # Redis may be back by the next renewal
            logger.exception(f"Could not renew the {kind.value} cache cleanup lock")


@contextmanager
def cleanup_lock(kind: CacheKind) -> Iterator[bool]:
    """Only one cleanup of a cache kind at a time. Yields whether this one got the lock.

    The lock expires soon unless it is renewed, which a thread does while the cleanup runs, so the
    lock of a cleanup that was killed does not hold up the next ones for long.
    """
    lock = redis_client.lock(
        f"cache:cleanup-lock:{kind.value}",
        timeout=CACHE_CLEANUP_LOCK_TTL,
        blocking=False,
        # Renewed from another thread
        thread_local=False,
    )
    if not lock.acquire():
        yield False
        return

    stop = threading.Event()
    renewal = threading.Thread(target=_renew_lock, args=(lock, kind, stop), daemon=True)
    renewal.start()
    try:
        yield True
    finally:
        stop.set()
        renewal.join()
        try:
            lock.release()
        except LockError:
            logger.warning(f"The {kind.value} cache cleanup lock expired before the release")


def enqueue_reclaim(
    kind: CacheKind,
    *,
    attempt: int = 1,
    previous_epoch: str | None = None,
    delay_seconds: int = 0,
    follow_up: bool = True,
    mark: bool = True,
) -> Job:
    """Queue a check of the retired epochs of the cache, see `reclaim_retired_cache`."""
    queue = get_queue(JobQueue.MEDIUM)
    args = (JobFn.RECLAIM_RETIRED_CACHE, kind.value, attempt, previous_epoch)
    kwargs = {
        "follow_up": follow_up,
        "mark": mark,
        "job_timeout": CACHE_CLEANUP_TIMEOUT,
        "meta": {"cid": cid_var.get()},
    }
    if delay_seconds:
        return queue.enqueue_in(timedelta(seconds=delay_seconds), *args, **kwargs)
    # Not scheduled: in burst mode a scheduled job waits for the next worker to start
    return queue.enqueue(*args, **kwargs)


def retired_roots(kind: CacheKind) -> list[Path]:
    """The directories of the cache kind that are not its current epoch."""
    former = [
        root
        for name in _FORMER_ROOTS.get(kind, ())
        if (root := settings.STORAGE_PATH / name).is_dir()
    ]

    kind_dir = _kind_dir(kind)
    if not kind_dir.is_dir():
        return former

    current = get_epoch(kind)
    current_name = epoch_dir_name(current) if current else None

    with os.scandir(kind_dir) as entries:
        return former + [
            Path(e.path)
            for e in entries
            if e.is_dir(follow_symlinks=False) and e.name != current_name
        ]


def has_unfinished_cleanup(kind: CacheKind) -> bool:
    """Whether a cleanup left retired epochs that it marked, or leftovers in the trash."""
    trash = _trash_dir(kind)
    if trash.is_dir() and any(trash.iterdir()):
        return True
    return any(_read_marker(root) is not None for root in retired_roots(kind))


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
    content = json.dumps(asdict(marker))
    tmp = root / f"{RETIRED_MARKER_FILE_NAME}.{uuid4().hex}.tmp"
    tmp.write_text(content)
    os.replace(tmp, root / RETIRED_MARKER_FILE_NAME)


def stamp_retired_roots(
    kind: CacheKind, previous_epoch: str | None, *, exclude_func_names: Collection[str]
) -> dict[Path, RetiredMarker | None]:
    """Write the marker into the retired epochs that do not have one yet. Returns the markers of
    all the retired epochs, None for the ones that could not be marked.

    The jobs recorded are the ones running now. For the epoch that was retired by the cleanup that
    calls this (`previous_epoch`), they include every job that could be using it: a job takes its
    epoch only once it is running.

    That does not hold for any other directory that is not marked yet. An epoch was retired by a
    cleanup that stopped before marking it, or Redis lost its data, which also loses the record of
    the jobs that are running, so the jobs listed now may be missing some that use that epoch. The
    layout from before the epochs is still used by the workers of the previous version during a
    deploy, and they start new jobs on it. Such a directory is marked as not trusted and is
    deleted only when it is old enough. If it turns out to be `previous_epoch` later on, e.g. it
    was marked by a check that did not know about the cleanup, it is marked again as trusted.
    """
    known_root = epoch_dir(kind, previous_epoch) if previous_epoch else None
    if known_root:
        # A job that took the previous epoch may not have created its directory yet. Created now,
        # the directory is marked with that job among the ones it waits for.
        try:
            known_root.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            logger.warning(f"Could not create the retired {kind.value} epoch {known_root}: {ex}")

    markers = {root: _read_marker(root) for root in retired_roots(kind)}
    to_mark = [
        root
        for root, marker in markers.items()
        if marker is None or (not marker.trusted and root == known_root)
    ]
    if not to_mark:
        return markers

    blocking = tuple(sorted(get_started_job_ids(exclude_func_names=exclude_func_names)))
    now = time.time()

    for root in to_mark:
        previous_marker = markers[root]
        marker = RetiredMarker(
            retired_at=previous_marker.retired_at if previous_marker else now,
            blocking_job_ids=blocking,
            trusted=root == known_root,
        )
        try:
            _write_marker(root, marker)
        except OSError as ex:
            logger.warning(f"Could not mark {root} as retired: {ex}")
            continue
        markers[root] = marker

    return markers


def _is_reclaimable(marker: RetiredMarker, now: float, unfinished_job_ids: set[str]) -> bool:
    if now - marker.retired_at >= settings.CACHE_RETIRED_MAX_AGE:
        return True
    return marker.trusted and unfinished_job_ids.isdisjoint(marker.blocking_job_ids)


def _delete(path: Path) -> bool:
    """Delete the tree. Returns whether it is gone, the delete only logs what it fails to remove."""
    rm_dir_parallel(path, workers=settings.CACHE_CLEANUP_WORKERS)
    return not path.exists()


def _purge_trash(kind: CacheKind) -> int:
    """Delete what an interrupted cleanup left behind. Returns how many could not be deleted."""
    trash = _trash_dir(kind)
    if not trash.is_dir():
        return 0
    return sum(not _delete(leftover) for leftover in trash.iterdir())


def reclaim_retired_roots(
    kind: CacheKind, markers: Mapping[Path, RetiredMarker | None] | None = None
) -> ReclaimResult:
    """Delete the retired epochs that no running job can be using any more.

    `markers` are the retired epochs with their markers, as `stamp_retired_roots` returns them.
    They are read again if not given.
    """
    result = ReclaimResult(pending=_purge_trash(kind))

    now = time.time()
    if markers is None:
        markers = {root: _read_marker(root) for root in retired_roots(kind)}
    roots = list(markers.items())

    # The retired epochs usually wait for the same jobs, so ask about them all at once
    blocking = {job_id for _, marker in roots if marker for job_id in marker.blocking_job_ids}
    unfinished = get_unfinished_job_ids(blocking) if blocking else set()

    for root, marker in roots:
        if marker is None or not _is_reclaimable(marker, now, unfinished):
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
        if _delete(trashed):
            result.reclaimed += 1
        else:
            # What is left is deleted by the purge of the trash, on the next check
            result.pending += 1

    return result
