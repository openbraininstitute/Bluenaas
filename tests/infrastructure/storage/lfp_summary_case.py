import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import fakeredis
from entitysdk.common import ProjectContext
from entitysdk.types import AssetLabel
from rq import Queue

from app.config.settings import settings
from app.infrastructure.rq import JobQueue, _queues, get_queue
from app.infrastructure.storage.epoch import CacheKind, ensure_epoch
from app.infrastructure.storage.lfp_summary import summary_dir
from tests.infrastructure.storage.fake_redis import FakeRedisTestCase


def report_of(size: int, label: AssetLabel = AssetLabel.lfp_report, is_directory: bool = False):
    return SimpleNamespace(id=uuid4(), size=size, label=label, is_directory=is_directory)


class LfpSummaryTestCase(FakeRedisTestCase):
    """A Redis that RQ runs on, the queues on it, and a storage of its own."""

    def setUp(self):
        super().setUp()
        self.redis = fakeredis.FakeRedis()
        for target in (
            "app.infrastructure.storage.epoch.redis_client",
            "app.infrastructure.storage.lfp_summary.redis_client",
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
        return ensure_epoch(CacheKind.LFP_SUMMARY)

    def summary_dir_of(self, asset_id) -> Path:
        directory = summary_dir(self.epoch(), asset_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def queued_ids(self, queue: JobQueue) -> list[str]:
        return get_queue(queue).get_job_ids()
