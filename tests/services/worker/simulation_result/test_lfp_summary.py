import hashlib
import json
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from filelock import FileLock
from loguru import logger

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.lfp_summary.summary import verify
from app.domains.simulation_result.lfp_summary import NoSummaryReason
from app.infrastructure.rq import JobQueue, get_queue
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
from tests.core.lfp_summary.utils import local_reader, write_nodes, write_report
from tests.infrastructure.storage.lfp_summary_case import LfpSummaryTestCase

URL = "https://bucket.s3/report.h5?signature"
NODES_URL = "https://bucket.s3/nodes.h5?signature"


class TestBuildLfpSummary(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        self.asset_id = uuid4()
        self.inputs = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.inputs)
        self.report = self.inputs / "lfp.h5"
        write_report(self.report)
        self.nodes_file = self.inputs / "nodes.h5"
        write_nodes(self.nodes_file, "pop", {"mtype": ["A", "B", "A"], "layer": ["5", "5", "5"]})

        self.urls: list[str] = []

        @contextmanager
        def http_ranges(url, *, connections):
            self.urls.append(url)
            read, size = local_reader(self.nodes_file if url == NODES_URL else self.report)
            yield SimpleNamespace(read=read, size=lambda: size)

        patcher = patch.object(service, "HttpRanges", side_effect=http_ranges)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_build(
        self,
        epoch: str | None = None,
        queue: JobQueue = JobQueue.LOW,
        url: str = URL,
        nodes: dict[str, str] | None = None,
    ):
        epoch = epoch or self.epoch()
        service.build_lfp_summary(
            self.asset_id,
            epoch=epoch,
            queue=queue,
            job_id=build_job_id(epoch, self.asset_id, queue),
            url=url,
            size=self.report.stat().st_size,
            nodes=nodes or {},
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

    def index(self) -> dict:
        return json.loads((self.directory() / INDEX_FILE_NAME).read_text())

    def test_the_cells_groups_come_from_the_nodes_file(self):
        self.run_build(nodes={"pop": NODES_URL})

        index = self.index()
        self.assertEqual(self.urls, [URL, NODES_URL])
        self.assertEqual([a["name"] for a in index["axes"]], ["total", "mtype"])
        self.assertEqual(index["axes"][1]["groups"], ["A", "B"])

    def test_without_nodes_only_the_total(self):
        self.run_build()

        self.assertEqual([a["name"] for a in self.index()["axes"]], ["total"])

    def test_nodes_that_cannot_be_read_leave_the_total(self):
        self.nodes_file.write_bytes(b"not an h5 file" * 100)

        self.run_build(nodes={"pop": NODES_URL})

        self.assertEqual([a["name"] for a in self.index()["axes"]], ["total"])

    def test_a_build_logs_its_stages_and_no_url(self):
        messages = []
        sink = logger.add(messages.append, format="{message}")
        self.addCleanup(logger.remove, sink)

        self.run_build(nodes={"pop": NODES_URL})

        logged = "".join(messages)
        self.assertIn("groups {'mtype': 2}", logged)
        self.assertIn(f"LFP report {self.asset_id}: read", logged)
        self.assertIn("written in", logged)
        self.assertIn("GiB of memory at most", logged)
        self.assertNotIn("signature", logged)

    def test_the_url_of_nodes_that_cannot_be_read_is_not_logged(self):
        self.nodes_file.write_bytes(b"not an h5 file" * 100)
        messages = []
        sink = logger.add(messages.append)
        self.addCleanup(logger.remove, sink)

        self.run_build(nodes={"pop": NODES_URL})

        self.assertFalse([m for m in messages if "signature" in m])

    def test_the_move_to_the_larger_queue_keeps_the_nodes(self):
        with patch.object(service, "memory_limit", return_value=1):
            self.run_build(nodes={"pop": NODES_URL})

        job = get_queue(JobQueue.CPU4_MEM16).fetch_job(
            build_job_id(self.epoch(), self.asset_id, JobQueue.CPU4_MEM16)
        )
        self.assertEqual(job.kwargs["nodes"], {"pop": NODES_URL})

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

    def test_a_summary_over_the_memory_of_low_is_moved_to_the_larger_queue(self):
        with patch.object(service, "memory_limit", return_value=1):
            self.run_build()

        directory = self.directory()
        self.assertFalse((directory / READY_MARKER_FILE_NAME).exists())
        self.assertFalse((directory / NO_SUMMARY_FILE_NAME).exists())
        self.assertFalse((directory / DIR_LOCK_FILE_NAME).exists())
        self.assertEqual(
            self.queued_ids(JobQueue.CPU4_MEM16),
            [build_job_id(self.epoch(), self.asset_id, JobQueue.CPU4_MEM16)],
        )

    def test_a_summary_over_the_memory_of_the_larger_queue_is_refused(self):
        with patch.object(service, "memory_limit", return_value=1):
            self.run_build(queue=JobQueue.CPU4_MEM16)

        marker = json.loads((self.directory() / NO_SUMMARY_FILE_NAME).read_text())
        self.assertEqual(marker["reason"], NoSummaryReason.TOO_LARGE.value)
        self.assertEqual(self.queued_ids(JobQueue.CPU4_MEM16), [])

    def url_with(self, seconds_left: int) -> str:
        lifetime = 6 * 3600
        signed = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(time.time() - lifetime + seconds_left))
        return f"https://bucket.s3/report.h5?X-Amz-Date={signed}&X-Amz-Expires={lifetime}"

    def test_nothing_is_read_by_a_url_that_expires_before_the_report_is_read(self):
        self.run_build(url=self.url_with(30))

        self.assertEqual(self.urls, [])
        self.assertFalse((self.directory() / NO_SUMMARY_FILE_NAME).exists())

    def test_a_url_needs_only_to_outlast_the_read(self):
        url = self.url_with(300)

        self.run_build(url=url)

        self.assertEqual(self.urls, [url])

    def test_a_url_is_needed_for_longer_by_a_larger_report(self):
        with patch.object(service, "READ_BYTES_PER_SECOND", 1):
            self.run_build(url=self.url_with(300))

        self.assertEqual(self.urls, [])

    def test_nothing_is_built_after_the_cache_was_cleared(self):
        epoch = self.epoch()
        rotate_epoch(CacheKind.LFP_SUMMARY)

        self.run_build(epoch=epoch)

        self.assertEqual(self.urls, [])
        self.assertFalse(summary_dir(epoch, self.asset_id).exists())
