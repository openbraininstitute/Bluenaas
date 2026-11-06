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

import httpx
from filelock import FileLock
from loguru import logger

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.lfp_summary.ranges import NoSuchFileError, RangeReadError
from app.core.lfp_summary.summary import verify
from app.domains.simulation_result.lfp_summary import GroupsUnavailable, NoSummaryReason
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch
from app.infrastructure.storage.lfp_summary import (
    INDEX_FILE_NAME,
    NO_SUMMARY_FILE_NAME,
    SUMMARY_FILE_NAME,
    SUMMARY_INFO_FILE_NAME,
    SummaryInfo,
    build_job_id,
    enqueue_build,
    read_summary_info,
    summary_dir,
)
from app.job.handlers.simulation_result import lfp_summary as handler
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
        self.nodes_failure: Exception | None = None

        @contextmanager
        def http_ranges(url, *, connections):
            self.urls.append(url)
            read, size = local_reader(self.nodes_file if url == NODES_URL else self.report)

            def size_of() -> int:
                if url == NODES_URL and self.nodes_failure:
                    raise self.nodes_failure
                return size

            yield SimpleNamespace(read=read, size=size_of)

        patcher = patch.object(service, "HttpRanges", side_effect=http_ranges)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_build(
        self,
        epoch: str | None = None,
        queue: JobQueue = JobQueue.LOW,
        url: str = URL,
        nodes: dict[str, str] | None = None,
        groups_unavailable: GroupsUnavailable | None = None,
        regroup: bool = False,
    ):
        epoch = epoch or self.epoch()
        service.build_lfp_summary(
            self.asset_id,
            epoch=epoch,
            queue=queue,
            job_id=build_job_id(epoch, self.asset_id, queue, regroup=regroup),
            url=url,
            size=self.report.stat().st_size,
            nodes=nodes or {},
            groups_unavailable=groups_unavailable,
            regroup=regroup,
        )

    def directory(self) -> Path:
        return summary_dir(self.epoch(), self.asset_id)

    def info(self) -> SummaryInfo:
        info = read_summary_info(self.directory())
        assert info is not None
        return info

    def test_a_build_writes_the_summary_its_index_and_info_then_ready(self):
        self.run_build()

        directory = self.directory()
        self.assertEqual(self.urls, [URL])
        self.assertTrue((directory / READY_MARKER_FILE_NAME).exists())
        info = self.info()
        summary = info.path(directory, SUMMARY_FILE_NAME).read_bytes()
        index_bytes = info.path(directory, INDEX_FILE_NAME).read_bytes()
        sha256 = hashlib.sha256(summary + index_bytes).hexdigest()
        self.assertEqual(
            json.loads((directory / SUMMARY_INFO_FILE_NAME).read_text()),
            {"size": len(summary), "sha256": sha256, "groups_unavailable": None},
        )
        self.assertEqual(info.path(directory, SUMMARY_FILE_NAME).name, f"summary.{sha256[:16]}.h5")
        index = json.loads(info.path(directory, INDEX_FILE_NAME).read_text())
        self.assertEqual(index["source"]["asset_id"], str(self.asset_id))
        verify(info.path(directory, SUMMARY_FILE_NAME), index)
        self.assertEqual(list(directory.glob("*.tmp")), [])

    def index(self) -> dict:
        return json.loads(self.info().path(self.directory(), INDEX_FILE_NAME).read_text())

    def test_a_circuit_that_could_not_be_read_is_said_why_there_are_no_groups(self):
        self.run_build(groups_unavailable=GroupsUnavailable.CIRCUIT_NOT_READABLE)

        self.assertEqual(self.index()["groups_unavailable"], "circuit_not_readable")
        self.assertEqual(self.info().groups_unavailable, "circuit_not_readable")

    def test_a_report_that_could_have_no_groups_is_not_said_to_lack_them(self):
        write_report(self.report, cells=1)

        self.run_build(groups_unavailable=GroupsUnavailable.CIRCUIT_NOT_READABLE)

        self.assertIsNone(self.index()["groups_unavailable"])
        self.assertIsNone(self.info().groups_unavailable)

    def test_a_summary_without_its_groups_is_replaced_by_one_with_them(self):
        self.run_build(groups_unavailable=GroupsUnavailable.CIRCUIT_NOT_READABLE)
        before = self.info()

        self.run_build(nodes={"pop": NODES_URL}, regroup=True)

        after = self.info()
        directory = self.directory()
        self.assertNotEqual(after.sha256, before.sha256)
        self.assertIsNone(after.groups_unavailable)
        self.assertEqual([a["name"] for a in self.index()["axes"]], ["total", "mtype"])
        verify(after.path(directory, SUMMARY_FILE_NAME), self.index())
        # Whoever reads the one replaced is answered 412 by its ETag
        self.assertFalse(before.path(directory, SUMMARY_FILE_NAME).exists())
        self.assertFalse(before.path(directory, INDEX_FILE_NAME).exists())

    def test_a_regroup_of_a_circuit_with_no_groups_to_give_is_a_new_summary(self):
        self.run_build(groups_unavailable=GroupsUnavailable.CIRCUIT_NOT_READABLE)
        before = self.info()

        self.run_build(regroup=True)

        # A new ETag, for a reader of the one before to read the new index
        self.assertNotEqual(self.info().sha256, before.sha256)
        self.assertIsNone(self.info().groups_unavailable)
        self.assertIsNone(self.index()["groups_unavailable"])

    def test_a_regroup_leaves_a_summary_with_its_groups_and_builds_none(self):
        self.run_build(nodes={"pop": NODES_URL})

        self.run_build(nodes={"pop": NODES_URL}, regroup=True)
        with self.subTest("nothing built"):
            self.assertEqual(self.urls, [URL, NODES_URL])

        self.asset_id = uuid4()
        self.run_build(nodes={"pop": NODES_URL}, regroup=True)
        self.assertIsNone(read_summary_info(self.directory()))

    def test_a_regroup_moved_to_the_larger_queue_stays_one(self):
        self.run_build(groups_unavailable=GroupsUnavailable.CIRCUIT_NOT_READABLE)

        with patch.object(service, "memory_limit", return_value=1):
            self.run_build(nodes={"pop": NODES_URL}, regroup=True)

        job = get_queue(JobQueue.CPU4_MEM16).fetch_job(
            build_job_id(self.epoch(), self.asset_id, JobQueue.CPU4_MEM16, regroup=True)
        )
        self.assertTrue(job.kwargs["regroup"])

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

    def test_a_nodes_file_that_is_not_there_leaves_the_total(self):
        self.nodes_failure = NoSuchFileError("no")

        self.run_build(nodes={"pop": NODES_URL})

        self.assertEqual([a["name"] for a in self.index()["axes"]], ["total"])

    def test_a_failed_read_of_the_nodes_keeps_a_summary_without_groups_out_of_the_cache(self):
        for failure in (RangeReadError("answered with 503"), httpx.ConnectTimeout("late")):
            with self.subTest(failure=failure):
                self.nodes_failure = failure

                with self.assertRaises(type(failure)):
                    self.run_build(nodes={"pop": NODES_URL})

                self.assertFalse((self.directory() / READY_MARKER_FILE_NAME).exists())
                self.assertFalse((self.directory() / NO_SUMMARY_FILE_NAME).exists())

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


class TestBuildJob(LfpSummaryTestCase):
    def test_a_queued_job_runs_with_all_it_was_queued_with(self):
        asset_id = uuid4()
        job = enqueue_build(
            JobQueue.LOW,
            epoch=self.epoch(),
            asset_id=asset_id,
            url="https://bucket.s3/report.h5",
            size=100,
            nodes={"pop": "https://bucket.s3/nodes.h5"},
            groups_unavailable=GroupsUnavailable.CIRCUIT_NOT_READABLE,
            regroup=True,
        )
        assert job is not None

        with (
            patch.object(handler, "build_lfp_summary") as build,
            patch.object(handler, "get_current_job_id", return_value=job.id),
        ):
            handler.build(**get_queue(JobQueue.LOW).fetch_job(job.id).kwargs)

        kwargs = build.call_args.kwargs
        self.assertEqual(build.call_args.args, (asset_id,))
        self.assertEqual(kwargs["queue"], JobQueue.LOW)
        self.assertEqual(kwargs["groups_unavailable"], GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.assertTrue(kwargs["regroup"])
