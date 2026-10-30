from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from unittest.mock import patch
from uuid import uuid4

import httpx
from entitysdk.types import AssetLabel
from rq.job import JobStatus

from app.constants import READY_MARKER_FILE_NAME
from app.core.exceptions import AppError
from app.domains.simulation_result.lfp_summary import LfpSummaryState, NoSummaryReason
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage import lfp_summary as storage
from app.infrastructure.storage.lfp_summary import (
    FAILED_BUILD_TTL,
    MAX_REPORT_BYTES,
    SMALL_REPORT_BYTES,
    SUMMARY_FILE_NAME,
    SummaryInfo,
    build_job_id,
    write_no_summary,
    write_summary_info,
)
from app.services.api.simulation_result import lfp_summary as service
from tests.infrastructure.storage.lfp_summary_case import LfpSummaryTestCase, report_of

URL = "https://bucket.s3/report.h5?signature"


class TestLfpSummaryStatus(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        self.result_id = uuid4()
        patcher = patch.object(service, "_download_url", return_value=URL)
        self.download_url = patcher.start()
        self.addCleanup(patcher.stop)

    def status_of(self, report):
        # In a thread, as the route runs it
        with ThreadPoolExecutor(1) as pool:
            return pool.submit(
                service._get_or_build_summary,
                self.result_id,
                report,
                access_token="token",
                project_context=self.project_context,
            ).result()

    def job_of(self, report, queue: JobQueue):
        return get_queue(queue).fetch_job(build_job_id(self.epoch(), report.id))

    def test_ready(self):
        report = report_of(100)
        directory = self.summary_dir_of(report.id)
        write_summary_info(directory, SummaryInfo(size=12, sha256="abc"))
        (directory / READY_MARKER_FILE_NAME).touch()

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.READY)
        self.assertEqual((status.size, status.sha256), (12, "abc"))
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_refused_by_its_marker(self):
        report = report_of(100)
        write_no_summary(self.summary_dir_of(report.id), NoSummaryReason.UNREADABLE, "units")

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.REFUSED)
        self.assertEqual(status.reason, NoSummaryReason.UNREADABLE)

    def test_refused_without_a_job(self):
        for report, reason in [
            (report_of(100, AssetLabel.spike_report), NoSummaryReason.NOT_LFP_REPORT),
            (report_of(100, is_directory=True), NoSummaryReason.NOT_LFP_REPORT),
            (report_of(MAX_REPORT_BYTES + 1), NoSummaryReason.TOO_LARGE),
        ]:
            with self.subTest(reason=reason):
                status = self.status_of(report)

                self.assertEqual(status.state, LfpSummaryState.REFUSED)
                self.assertEqual(status.reason, reason)
                self.assertEqual(self.queued_ids(JobQueue.LOW), [])
                self.assertEqual(self.queued_ids(JobQueue.CPU4_MEM16), [])

    def test_a_report_labelled_as_voltages_is_summarised(self):
        report = report_of(100, AssetLabel.voltage_report)

        self.assertEqual(self.status_of(report).state, LfpSummaryState.BUILDING)

    def test_the_queue_is_chosen_by_the_report_size(self):
        for size, queue in [
            (1, JobQueue.LOW),
            (SMALL_REPORT_BYTES, JobQueue.LOW),
            (SMALL_REPORT_BYTES + 1, JobQueue.CPU4_MEM16),
            (MAX_REPORT_BYTES, JobQueue.CPU4_MEM16),
        ]:
            with self.subTest(size=size):
                report = report_of(size)

                status = self.status_of(report)

                self.assertEqual(status.state, LfpSummaryState.BUILDING)
                self.assertIn(build_job_id(self.epoch(), report.id), self.queued_ids(queue))

    def test_the_job_queued(self):
        report = report_of(100)

        self.status_of(report)

        job = self.job_of(report, JobQueue.LOW)
        self.assertEqual(job.kwargs["asset_id"], report.id)
        self.assertEqual(job.kwargs["epoch"], self.epoch())
        self.assertEqual(job.kwargs["url"], URL)
        self.assertEqual(job.kwargs["size"], 100)
        self.assertEqual(job.retries_left, 1)
        self.assertEqual(job.failure_ttl, FAILED_BUILD_TTL)
        self.assertEqual(
            job.failure_callback,
            storage.remove_build_leftovers,  # type: ignore[attr-defined]
        )

    def test_no_second_job_while_one_is_queued(self):
        report = report_of(100)
        self.status_of(report)

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.BUILDING)
        self.assertEqual(status.queue_position, 0)
        self.assertEqual(len(self.queued_ids(JobQueue.LOW)), 1)
        self.assertEqual(self.download_url.call_count, 1)

    def test_failed_after_its_retry(self):
        report = report_of(100)
        self.status_of(report)
        self.job_of(report, JobQueue.LOW).set_status(JobStatus.FAILED)

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.FAILED)

    def test_a_new_format_version_is_built_again(self):
        report = report_of(100)
        directory = self.summary_dir_of(report.id)
        write_summary_info(directory, SummaryInfo(size=12, sha256="abc"))
        (directory / READY_MARKER_FILE_NAME).touch()

        with patch.object(storage, "FORMAT_VERSION", storage.FORMAT_VERSION + 1):
            status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.BUILDING)


class TestDownloadUrl(LfpSummaryTestCase):
    def url_answered_by(self, response: httpx.Response) -> str:
        with patch.object(service.httpx, "get", return_value=response) as get:
            url = service._download_url(
                uuid4(), uuid4(), access_token="token", project_context=self.project_context
            )
        self.headers = get.call_args.kwargs["headers"]
        return url

    def test_the_redirect_of_the_download(self):
        response = httpx.Response(307, headers={"location": URL})

        self.assertEqual(self.url_answered_by(response), URL)
        self.assertEqual(self.headers["Authorization"], "Bearer token")
        self.assertEqual(self.headers["project-id"], str(self.project_context.project_id))

    def test_no_redirect(self):
        with self.assertRaises(AppError) as caught:
            self.url_answered_by(httpx.Response(200, content=b"the file"))

        self.assertEqual(caught.exception.http_status_code, HTTPStatus.BAD_GATEWAY)


class TestSummaryFile(LfpSummaryTestCase):
    def build(self, asset_id) -> str:
        directory = self.summary_dir_of(asset_id)
        (directory / SUMMARY_FILE_NAME).write_bytes(b"summary")
        write_summary_info(directory, SummaryInfo(size=7, sha256="abc"))
        (directory / READY_MARKER_FILE_NAME).touch()
        return '"abc"'

    def test_if_match(self):
        asset_id = uuid4()
        etag = self.build(asset_id)

        for if_match, served in [
            (None, True),
            ("*", True),
            (etag, True),
            (f'"other", {etag}', True),
            ('"other"', False),
            ("abc", False),
        ]:
            with self.subTest(if_match=if_match):
                if served:
                    response = service._summary_file_response(
                        asset_id, SUMMARY_FILE_NAME, "application/x-hdf5", if_match
                    )
                    self.assertEqual(response.headers["etag"], etag)
                else:
                    with self.assertRaises(AppError) as caught:
                        service._summary_file_response(
                            asset_id, SUMMARY_FILE_NAME, "application/x-hdf5", if_match
                        )
                    self.assertEqual(
                        caught.exception.http_status_code, HTTPStatus.PRECONDITION_FAILED
                    )

    def test_not_built(self):
        with self.assertRaises(AppError) as caught:
            service._summary_file_response(uuid4(), SUMMARY_FILE_NAME, "application/x-hdf5", None)

        self.assertEqual(caught.exception.http_status_code, HTTPStatus.NOT_FOUND)
