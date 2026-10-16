from rq import Queue

from app.context import cid_var
from app.infrastructure.storage.epoch import CacheKind
from app.job import JobFn
from app.utils.asyncio import run_async


async def start_cache_cleanup(kind: CacheKind, *, job_queue: Queue, description: str) -> dict:
    """Start cleaning up the cache in the background. The result is the id of the cleanup job."""
    job = await run_async(
        lambda: job_queue.enqueue(
            JobFn.CLEAR_CACHE,
            kind.value,
            meta={"cid": cid_var.get()},
        )
    )
    return {"message": f"{description} cleanup started", "job_id": job.id}
