import asyncio

from loguru import logger

from app.infrastructure.storage.cache import enqueue_reclaim
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch


def _clear_cache(kind: CacheKind) -> str:
    previous = rotate_epoch(kind)
    logger.info(f"Started a new {kind.value} cache epoch, the previous one was {previous}")

    # A job takes its epochs once it is among the started jobs, so every job that might use the
    # previous epoch is listed there by now
    job = enqueue_reclaim(kind, previous_epoch=previous)
    return job.id


async def start_cache_cleanup(kind: CacheKind) -> dict:
    """Start a new epoch of the cache, so that no new job uses the old one, and queue the deletion
    of the old one. The result is the id of the job that deletes it.

    This does not wait for anything, so it takes effect even if another cleanup is running.
    """
    job_id = await asyncio.to_thread(_clear_cache, kind)
    description = kind.value.replace("-", " ").capitalize()
    return {"message": f"{description} cache cleanup started", "job_id": job_id}
