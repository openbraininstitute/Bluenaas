import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID

import httpx
import numpy as np
from filelock import FileLock, Timeout
from loguru import logger

from app.config.settings import settings
from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.lfp_summary.nodes import cell_labels
from app.core.lfp_summary.ranges import HttpRanges, RangeReadError, url_expires_at
from app.core.lfp_summary.summary import (
    READS_IN_FLIGHT,
    CellLabels,
    NotSummarisableError,
    OverMemoryError,
    sum_report,
    verify,
    write_summary,
)
from app.domains.simulation_result.lfp_summary import NoSummaryReason
from app.infrastructure.rq import JobQueue
from app.infrastructure.storage import write_atomically
from app.infrastructure.storage.epoch import CacheKind, current_epoch
from app.utils.memory import memory_limit
from app.infrastructure.storage.lfp_summary import (
    FORMAT_VERSION,
    INDEX_FILE_NAME,
    NO_SUMMARY_FILE_NAME,
    READ_BYTES_PER_SECOND,
    SUMMARY_FILE_NAME,
    SummaryInfo,
    enqueue_build,
    summary_dir,
    write_no_summary,
    write_summary_info,
)

# What a URL must have left besides the time its report takes to read
URL_MARGIN_SECONDS = 60


def _is_settled(directory: Path) -> bool:
    return (directory / READY_MARKER_FILE_NAME).exists() or (
        directory / NO_SUMMARY_FILE_NAME
    ).exists()


def _labels_from(nodes: dict[str, str]) -> CellLabels:
    """A population's cells' labels from its nodes file. None if that can't be read: the report is
    still summarised, and without its groups.
    """

    def labels_of(population: str, node_ids: np.ndarray) -> dict[str, np.ndarray]:
        url = nodes.get(population)
        if url is None:
            return {}
        try:
            with HttpRanges(url, connections=READS_IN_FLIGHT) as ranges:
                return cell_labels(ranges.read, ranges.size(), population, node_ids)
        except (OSError, ValueError, IndexError, RangeReadError, httpx.TransportError) as ex:
            # Its type alone: the message of some of these holds the URL's signature
            logger.warning(f"The nodes of {population} can't be read: {type(ex).__name__}")
            return {}

    return labels_of


def _build(
    asset_id: UUID,
    directory: Path,
    *,
    queue: JobQueue,
    job_id: str,
    url: str,
    size: int,
    nodes: dict[str, str],
) -> bool:
    """Build the summary, or leave the reason there is none. Returns whether it takes more memory
    than this queue's share but maybe not a larger one's.
    """
    with HttpRanges(url, connections=READS_IN_FLIGHT) as ranges:
        try:
            report = sum_report(
                ranges.read,
                size,
                labels_of=_labels_from(nodes),
                memory=memory_limit() // settings.NUM_WORKERS,
                move_for_groups=queue == JobQueue.LOW,
            )
        except NotSummarisableError as ex:
            logger.info(f"The LFP report {asset_id} is not summarised: {ex}")
            write_no_summary(directory, ex.reason, str(ex))
            return False
        except OverMemoryError as ex:
            if queue == JobQueue.LOW:
                logger.info(f"The LFP summary of {asset_id} is too large for {queue.value}: {ex}")
                return True
            write_no_summary(directory, NoSummaryReason.TOO_LARGE, str(ex))
            return False

    tmp = directory / f"{SUMMARY_FILE_NAME}.{job_id}.tmp"
    index = write_summary(
        report,
        tmp,
        version=FORMAT_VERSION,
        source={"asset_id": str(asset_id), "size": size},
    )
    verify(tmp, index)
    with tmp.open("rb") as f:
        sha256 = hashlib.file_digest(f, "sha256").hexdigest()
    summary_size = tmp.stat().st_size
    os.replace(tmp, directory / SUMMARY_FILE_NAME)
    write_atomically(directory / INDEX_FILE_NAME, json.dumps(index))
    write_summary_info(directory, SummaryInfo(size=summary_size, sha256=sha256))
    (directory / READY_MARKER_FILE_NAME).touch()
    logger.info(f"LFP summary of {asset_id} built, {summary_size} bytes")
    return False


def build_lfp_summary(
    asset_id: UUID,
    *,
    epoch: str,
    queue: JobQueue,
    job_id: str,
    url: str,
    size: int,
    nodes: dict[str, str],
) -> None:
    """Build the report's summary into the cache, unless it is there or another build holds it.

    A build on `low` that would go over its worker's share of the memory is moved to `4cpu-16gb`.
    """
    if current_epoch(CacheKind.LFP_SUMMARY) != epoch:
        # The next request for the summary queues it in the new epoch
        logger.info("The LFP summary cache was cleared since the build was queued")
        return

    directory = summary_dir(epoch, asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    if _is_settled(directory):
        return

    expires_at = url_expires_at(url)
    needed = URL_MARGIN_SECONDS + size / READ_BYTES_PER_SECOND
    if expires_at is not None and (left := expires_at - time.time()) < needed:
        # Finished, not failed: the next request for the summary queues it with a new URL. A URL too
        # short even when new would repeat this on every poll, so it is a warning.
        logger.warning(
            f"The URL of the LFP report {asset_id} has {left:.0f} s left, its read needs {needed:.0f} s"
        )
        return

    # Not waiting: the one holding the lock builds the same summary
    lock = FileLock(directory / DIR_LOCK_FILE_NAME)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info(f"Another job is building the LFP summary of {asset_id}")
        return

    try:
        too_large = not _is_settled(directory) and _build(
            asset_id, directory, queue=queue, job_id=job_id, url=url, size=size, nodes=nodes
        )
    finally:
        lock.release()

    if too_large:
        # Queued once the lock is free, so the larger build doesn't find it held
        enqueue_build(
            JobQueue.CPU4_MEM16, epoch=epoch, asset_id=asset_id, url=url, size=size, nodes=nodes
        )
