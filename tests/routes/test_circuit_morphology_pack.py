import hashlib
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
from app.infrastructure.storage.morphology_pack import (
    PACK_FILE_NAME,
    PackInfo,
    build_job_id,
    write_pack_info,
)
from app.services.api.circuit import morphology_pack as service
from tests.infrastructure.storage.morphology_pack_case import MorphologyPackTestCase, circuit_of

CONTENT = bytes(range(100))


class TestMorphologyPackRoutes(MorphologyPackTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.circuit = circuit_of(100)
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

        patcher = patch.object(service, "_get_circuit", return_value=self.circuit)
        self.get_circuit = patcher.start()
        self.addCleanup(patcher.stop)

    def url(self) -> str:
        return f"/circuit/{self.circuit.id}/morphology-pack"

    def build(self) -> str:
        directory = self.pack_dir_of(self.circuit.id)
        sha256 = hashlib.sha256(CONTENT).hexdigest()
        (directory / PACK_FILE_NAME).write_bytes(CONTENT)
        write_pack_info(directory, PackInfo(size=len(CONTENT), sha256=sha256, queue="low"))
        (directory / READY_MARKER_FILE_NAME).touch()
        return sha256

    def test_post_queues_the_build(self):
        response = self.client.post(self.url(), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()["state"], "building")
        self.assertEqual(
            self.queued_ids(JobQueue.LOW),
            [build_job_id(self.epoch(), self.circuit.id, JobQueue.LOW)],
        )

    def test_post_of_a_ready_pack(self):
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
        response = self.client.get(self.url(), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_get_checks_access_before_it_serves(self):
        self.build()
        self.get_circuit.side_effect = AppError(
            message="Circuit not found", error_code=None, http_status_code=HTTPStatus.NOT_FOUND
        )

        response = self.client.get(self.url(), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)
        self.assertNotEqual(response.content, CONTENT)

    def test_get_the_whole_pack(self):
        sha256 = self.build()

        response = self.client.get(self.url(), headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.content, CONTENT)
        self.assertEqual(response.headers["etag"], f'"{sha256}"')
        self.assertEqual(response.headers["content-type"], "application/octet-stream")

    def test_get_the_rest_of_a_cut_download(self):
        self.build()

        response = self.client.get(self.url(), headers={**self.headers, "Range": "bytes=40-"})

        self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
        self.assertEqual(response.content, CONTENT[40:])
        self.assertEqual(response.headers["content-length"], str(len(CONTENT) - 40))
        self.assertEqual(response.headers["content-range"], f"bytes 40-99/{len(CONTENT)}")

    def test_unknown_circuit(self):
        self.get_circuit.side_effect = AppError(
            message="Circuit not found", error_code=None, http_status_code=HTTPStatus.NOT_FOUND
        )

        response = self.client.post(f"/circuit/{uuid4()}/morphology-pack", headers=self.headers)

        self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])
