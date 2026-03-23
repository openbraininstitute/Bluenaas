from loguru import logger
from rq.job import Job
from rq.queue import Queue
from rq.worker import SimpleWorker

from app.constants import NULL_CID
from app.context import cid_var
from app.logging import setup_logging


class LoggingWorker(SimpleWorker):
    def __init__(self, *args, **kwargs):
        setup_logging()
        super().__init__(*args, **kwargs)

    def perform_job(self, job: Job, queue: Queue) -> bool:
        cid = job.meta.get("cid") or NULL_CID
        cid_var.set(cid)
        with logger.contextualize(cid=cid):
            return super().perform_job(job, queue)
