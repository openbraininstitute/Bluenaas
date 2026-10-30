import hashlib
import json
import os
from http import HTTPStatus
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from fastapi.testclient import TestClient

from app.app import app
from app.constants import READY_MARKER_FILE_NAME
from app.core.exceptions import AppError
from app.infrastructure.rq import JobQueue
from app.infrastructure.storage.lfp_summary import (
    INDEX_FILE_NAME,
    SUMMARY_FILE_NAME,
    SummaryInfo,
    build_job_id,
    write_summary_info,
)
from app.services.api.simulation_result import lfp_summary as service
from tests.infrastructure.storage.lfp_summary_case import LfpSummaryTestCase, report_of

CONTENT = bytes(range(100))
INDEX = {"format": "lfp-summary", "version": 1}


class TestLfpSummaryRoutes(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.result_id = uuid4()
        self.report = report_of(100)
        self.headers = {
            "Authorization": "Bearer token",
            "project-id": str(self.project_context.project_id),
            "virtual-lab-id": str(self.project_context.virtual_lab_id),
        }

        patcher = patch("app.infrastructure.kc.auth.kc_auth")
        kc_auth = patcher.start()
        self.addCleanup(patcher.stop)
        kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "user-123",
            "preferred_username": "user",
            "email": "user@example.com",
        }

        patcher = patch.object(service, "_get_report", return_value=self.report)
        self.get_report = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(service, "_download_url", return_value="https://bucket/report.h5")
        patcher.start()
        self.addCleanup(patcher.stop)

    def url(self, part: str = "") -> str:
        return f"/simulation-result/{self.result_id}/lfp-summary{part}?asset={self.report.id}"

    def build(self) -> str:
        directory = self.summary_dir_of(self.report.id)
        sha256 = hashlib.sha256(CONTENT).hexdigest()
        (directory / SUMMARY_FILE_NAME).write_bytes(CONTENT)
        (directory / INDEX_FILE_NAME).write_text(json.dumps(INDEX))
        write_summary_info(directory, SummaryInfo(size=len(CONTENT), sha256=sha256))
        (directory / READY_MARKER_FILE_NAME).touch()
        return sha256

    def test_post_queues_the_build(self):
        response = self.client.post(self.url(), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()["state"], "building")
        self.assertEqual(
            self.queued_ids(JobQueue.LOW),
            [build_job_id(self.epoch(), self.report.id, JobQueue.LOW)],
        )
        self.get_report.assert_called_once()
        self.assertEqual(self.get_report.call_args.args, (self.result_id, self.report.id))

    def test_post_of_a_ready_summary(self):
        sha256 = self.build()

        response = self.client.post(self.url(), headers=self.headers)

        self.assertEqual(
            response.json(),
            {
                "state": "ready",
                "size": len(CONTENT),
                "sha256": sha256,
                "queue_position": None,
                "reason": None,
            },
        )

    def test_get_before_it_is_built(self):
        for part in ("", "/index"):
            with self.subTest(part=part):
                response = self.client.get(self.url(part), headers=self.headers)

                self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)
                self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_get_checks_access_before_it_serves(self):
        self.build()
        self.get_report.side_effect = AppError(
            message="Simulation result not found",
            error_code=None,
            http_status_code=HTTPStatus.NOT_FOUND,
        )

        response = self.client.get(self.url(), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)
        self.assertNotEqual(response.content, CONTENT)

    def test_get_a_range(self):
        sha256 = self.build()

        response = self.client.get(
            self.url(),
            headers={**self.headers, "Range": "bytes=40-49", "If-Match": f'"{sha256}"'},
        )

        self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
        self.assertEqual(response.content, CONTENT[40:50])
        self.assertEqual(response.headers["content-range"], f"bytes 40-49/{len(CONTENT)}")
        self.assertEqual(response.headers["etag"], f'"{sha256}"')

    def test_get_of_another_summary_than_the_one_built(self):
        self.build()

        response = self.client.get(
            self.url(), headers={**self.headers, "Range": "bytes=40-49", "If-Match": '"old"'}
        )

        self.assertEqual(response.status_code, HTTPStatus.PRECONDITION_FAILED)

    def test_get_the_index(self):
        self.build()

        response = self.client.get(self.url("/index"), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json(), INDEX)
        self.assertEqual(response.headers["content-type"], "application/json")

    def test_cors_exposes_the_range_headers(self):
        sha256 = self.build()

        response = self.client.get(
            self.url(),
            headers={**self.headers, "Range": "bytes=0-9", "Origin": "http://localhost:3000"},
        )

        exposed = response.headers.get("access-control-expose-headers", "")
        for header in ("Content-Range", "ETag"):
            self.assertIn(header, exposed)
        self.assertEqual(response.headers["etag"], f'"{sha256}"')
