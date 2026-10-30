import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import fakeredis
from entitysdk.common import ProjectContext
from entitysdk.types import CircuitScale
from rq import Queue
from rq.job import Job, JobStatus

from app.config.settings import settings
from app.infrastructure.rq import JobQueue, _queues, get_queue
from app.infrastructure.storage.epoch import CacheKind, ensure_epoch
from app.infrastructure.storage.morphology_pack import pack_dir
from tests.infrastructure.storage.fake_redis import FakeRedisTestCase


def circuit_of(number_neurons: int, scale: CircuitScale = CircuitScale.microcircuit):
    return SimpleNamespace(id=uuid4(), number_neurons=number_neurons, scale=scale)


class MorphologyPackTestCase(FakeRedisTestCase):
    """A Redis that RQ runs on, the queues on it, and a storage of its own."""

    def setUp(self):
        super().setUp()
        self.redis = fakeredis.FakeRedis()
        for target in (
            "app.infrastructure.storage.epoch.redis_client",
            "app.infrastructure.storage.morphology_pack.redis_client",
        ):
            patcher = patch(target, self.redis)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = patch.dict(
            _queues, {queue: Queue(queue.value, connection=self.redis) for queue in JobQueue}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.storage = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.storage)
        patcher = patch.object(settings, "STORAGE_PATH", self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.project_context = ProjectContext(project_id=uuid4(), virtual_lab_id=uuid4())

    def epoch(self) -> str:
        return ensure_epoch(CacheKind.MORPHOLOGY_PACK)

    def pack_dir_of(self, circuit_id) -> Path:
        directory = pack_dir(self.epoch(), circuit_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def queued_ids(self, queue: JobQueue) -> list[str]:
        return get_queue(queue).get_job_ids()

    def abandon(self, job: Job) -> None:
        """Make the job look started by a worker that died 90 s ago, with the last cleanup of its
        queue far enough behind.
        """
        queue = get_queue(JobQueue(job.origin))
        queue.remove(job)
        job.set_status(JobStatus.STARTED)
        self.redis.zadd(queue.started_job_registry.key, {f"{job.id}:execution": time.time() - 1})
        self.redis.delete(f"morphology-pack:cleanup:{queue.name}")
