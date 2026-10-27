from loguru import logger
from rq.job import Job
from rq.queue import Queue
from rq.worker import Worker

from app.constants import NULL_CID
from app.context import cid_var
from app.infrastructure.storage.epoch import clear_pinned_epochs
from app.logging import setup_logging
from app.services.worker.admin.cache import start_pending_reclaims


class LoggingWorker(Worker):
    def __init__(self, *args, **kwargs):
        setup_logging()
        super().__init__(*args, **kwargs)

    def work(self, *args, **kwargs) -> bool:
        # Picks up the cache cleanups that were cut short
        start_pending_reclaims()
        return super().work(*args, **kwargs)

    def perform_job(self, job: Job, queue: Queue) -> bool:
        cid = job.meta.get("cid") or NULL_CID
        cid_var.set(cid)
        # Each job picks the cache epochs it works with. The job runs in a process forked for it,
        # so this only matters if a pin ever leaks from the worker process itself.
        clear_pinned_epochs()
        with logger.contextualize(cid=cid):
            return super().perform_job(job, queue)
