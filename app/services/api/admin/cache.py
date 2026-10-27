from contextvars import copy_context

from loguru import logger

from app.config.settings import settings
from app.infrastructure.storage.cache import schedule_reclaim
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch
from app.utils.asyncio import run_async


def _clear_cache(kind: CacheKind) -> str:
    previous = rotate_epoch(kind)
    logger.info(f"Started a new {kind.value} cache epoch, the previous one was {previous}")

    # Jobs that started a moment ago may not have seen the new epoch yet, so the jobs that might
    # use the previous one are listed only after a pause
    job = schedule_reclaim(
        kind,
        attempt=1,
        previous_epoch=previous,
        delay_seconds=settings.CACHE_EPOCH_SETTLE_SECONDS,
    )
    return job.id


async def start_cache_cleanup(kind: CacheKind, *, description: str) -> dict:
    """Start a new epoch of the cache, so that no new job uses the old one, and schedule the
    deletion of the old one. The result is the id of the job that deletes it.

    This does not wait for anything, so it takes effect even if another cleanup is running.
    """
    # The executor thread does not get the context, and with it the cid, by itself
    job_id = await run_async(copy_context().run, _clear_cache, kind)
    return {"message": f"{description} cleanup started", "job_id": job_id}
