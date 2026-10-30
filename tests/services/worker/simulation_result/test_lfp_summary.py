import hashlib
import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from filelock import FileLock

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.lfp_summary.summary import verify
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch
from app.infrastructure.storage.lfp_summary import (
    INDEX_FILE_NAME,
    NO_SUMMARY_FILE_NAME,
    SUMMARY_FILE_NAME,
    SUMMARY_INFO_FILE_NAME,
    build_job_id,
    summary_dir,
)
from app.services.worker.simulation_result import lfp_summary as service
from tests.core.lfp_summary.utils import local_reader, write_report
from tests.infrastructure.storage.lfp_summary_case import LfpSummaryTestCase

URL = "https://bucket.s3/report.h5?signature"


class TestBuildLfpSummary(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        self.asset_id = uuid4()
        self.inputs = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.inputs)
        self.report = self.inputs / "lfp.h5"
        write_report(self.report)

        self.urls: list[str] = []

        @contextmanager
        def http_ranges(url, *, connections):
            self.urls.append(url)
            read, _ = local_reader(self.report)
            yield SimpleNamespace(read=read)

        patcher = patch.object(service, "HttpRanges", side_effect=http_ranges)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_build(self, epoch: str | None = None):
        epoch = epoch or self.epoch()
        service.build_lfp_summary(
            self.asset_id,
            epoch=epoch,
            job_id=build_job_id(epoch, self.asset_id),
            url=URL,
            size=self.report.stat().st_size,
        )

    def directory(self) -> Path:
        return summary_dir(self.epoch(), self.asset_id)

    def test_a_build_writes_the_summary_its_index_and_info_then_ready(self):
        self.run_build()

        directory = self.directory()
        self.assertEqual(self.urls, [URL])
        self.assertTrue((directory / READY_MARKER_FILE_NAME).exists())
        summary = (directory / SUMMARY_FILE_NAME).read_bytes()
        self.assertEqual(
            json.loads((directory / SUMMARY_INFO_FILE_NAME).read_text()),
            {
                "size": len(summary),
                "sha256": hashlib.sha256(summary).hexdigest(),
            },
        )
        index = json.loads((directory / INDEX_FILE_NAME).read_text())
        self.assertEqual(index["source"]["asset_id"], str(self.asset_id))
        verify(directory / SUMMARY_FILE_NAME, index)
        self.assertEqual(list(directory.glob("*.tmp")), [])

    def test_a_file_that_is_no_report_is_marked(self):
        self.report.write_bytes(b"not an h5 file" * 100)

        self.run_build()

        directory = self.directory()
        marker = json.loads((directory / NO_SUMMARY_FILE_NAME).read_text())
        self.assertEqual(marker["reason"], "not_lfp_report")
        self.assertFalse((directory / READY_MARKER_FILE_NAME).exists())

    def test_nothing_is_read_once_it_is_settled(self):
        self.run_build()

        self.run_build()

        self.assertEqual(self.urls, [URL])

    def test_nothing_is_built_while_another_build_holds_the_lock(self):
        directory = self.directory()
        directory.mkdir(parents=True)
        lock = FileLock(directory / DIR_LOCK_FILE_NAME)
        lock.acquire()
        self.addCleanup(lock.release)

        self.run_build()

        self.assertEqual(self.urls, [])
        self.assertFalse((directory / READY_MARKER_FILE_NAME).exists())

    def test_nothing_is_built_after_the_cache_was_cleared(self):
        epoch = self.epoch()
        rotate_epoch(CacheKind.LFP_SUMMARY)

        self.run_build(epoch=epoch)

        self.assertEqual(self.urls, [])
        self.assertFalse(summary_dir(epoch, self.asset_id).exists())
