import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from filelock import FileLock, Timeout
from loguru import logger

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.lfp_summary.ranges import HttpRanges
from app.core.lfp_summary.summary import (
    READS_IN_FLIGHT,
    NotSummarisableError,
    sum_report,
    verify,
    write_summary,
)
from app.infrastructure.storage import write_atomically
from app.infrastructure.storage.epoch import CacheKind, current_epoch
from app.infrastructure.storage.lfp_summary import (
    FORMAT_VERSION,
    INDEX_FILE_NAME,
    NO_SUMMARY_FILE_NAME,
    SUMMARY_FILE_NAME,
    SummaryInfo,
    summary_dir,
    write_no_summary,
    write_summary_info,
)


def _is_settled(directory: Path) -> bool:
    return (directory / READY_MARKER_FILE_NAME).exists() or (
        directory / NO_SUMMARY_FILE_NAME
    ).exists()


def _build(asset_id: UUID, directory: Path, *, job_id: str, url: str, size: int) -> None:
    """Build the summary, or leave the reason there is none."""
    with HttpRanges(url, connections=READS_IN_FLIGHT) as ranges:
        try:
            report = sum_report(ranges.read, size)
        except NotSummarisableError as ex:
            logger.info(f"The LFP report {asset_id} is not summarised: {ex}")
            write_no_summary(directory, ex.reason, str(ex))
            return

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


def build_lfp_summary(asset_id: UUID, *, epoch: str, job_id: str, url: str, size: int) -> None:
    """Build the report's summary into the cache, unless it is there or another build holds it."""
    if current_epoch(CacheKind.LFP_SUMMARY) != epoch:
        # The next request for the summary queues it in the new epoch
        logger.info("The LFP summary cache was cleared since the build was queued")
        return

    directory = summary_dir(epoch, asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    if _is_settled(directory):
        return

    # Not waiting: the one holding the lock builds the same summary
    lock = FileLock(directory / DIR_LOCK_FILE_NAME)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info(f"Another job is building the LFP summary of {asset_id}")
        return

    try:
        if not _is_settled(directory):
            _build(asset_id, directory, job_id=job_id, url=url, size=size)
    finally:
        lock.release()
