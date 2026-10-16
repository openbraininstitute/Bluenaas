from loguru import logger
from rq.job import Job
from rq.queue import Queue
from rq.worker import Worker

from app.constants import NULL_CID
from app.context import cid_var
from app.infrastructure.storage.epoch import clear_pinned_epochs
from app.logging import setup_logging


class LoggingWorker(Worker):
    def __init__(self, *args, **kwargs):
        setup_logging()
        super().__init__(*args, **kwargs)

    def perform_job(self, job: Job, queue: Queue) -> bool:
        cid = job.meta.get("cid") or NULL_CID
        cid_var.set(cid)
        # Each job picks the cache epochs it works with, nothing carries over from a previous one
        clear_pinned_epochs()
        with logger.contextualize(cid=cid):
            return super().perform_job(job, queue)
