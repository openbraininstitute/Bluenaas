import os
import unittest
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import MagicMock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from fastapi.testclient import TestClient

from app.app import app
from app.config.settings import settings
from app.context import cid_var
from app.domains.auth import Auth, DecodedKeycloakToken
from app.infrastructure.rq import JobQueue, _queues
from app.infrastructure.storage.epoch import CacheKind
from app.job import JobFn
from app.services.api.admin import cache as service


class TestAdminRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.admin_auth = Auth(
            access_token="admin-token",
            decoded_token=DecodedKeycloakToken(
                exp=1234567890,
                iss="http://localhost:9090/",
                sub="admin-123",
                preferred_username="admin",
                email="admin@example.com",
                groups=["/service/small-scale-simulator/admin"],
            ),
        )

    def _authorize_admin(self, mock_kc_auth):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "admin-123",
            "preferred_username": "admin",
            "email": "admin@example.com",
        }
        mock_kc_auth.userinfo.return_value = {"groups": ["/service/small-scale-simulator/admin"]}

    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_cache_starts_a_new_epoch_and_schedules_the_reclaim(self, mock_kc_auth):
        self._authorize_admin(mock_kc_auth)

        cases = [
            ("circuit", CacheKind.CIRCUIT, "Circuit cache cleanup started"),
            ("single-neuron", CacheKind.SINGLE_NEURON, "Single neuron cache cleanup started"),
            ("mesh", CacheKind.MESH, "Mesh cache cleanup started"),
            ("task-config", CacheKind.TASK_CONFIG, "Task config cache cleanup started"),
            ("compilation", CacheKind.COMPILATION, "Compilation cache cleanup started"),
        ]

        for endpoint, kind, message in cases:
            with self.subTest(endpoint=endpoint):
                mock_queue = MagicMock()
                mock_queue.enqueue_in.return_value.id = "job-1"

                with (
                    patch.dict(_queues, {JobQueue.MEDIUM: mock_queue}),
                    patch.object(service, "rotate_epoch", return_value="previous") as rotate,
                ):
                    response = self.client.delete(
                        f"/admin/cache/{endpoint}", headers={"Authorization": "Bearer admin-token"}
                    )

                self.assertEqual(response.status_code, HTTPStatus.ACCEPTED)
                self.assertEqual(response.json(), {"message": message, "job_id": "job-1"})
                rotate.assert_called_once_with(kind)
                # Jobs that started a moment ago may not have seen the new epoch yet
                mock_queue.enqueue_in.assert_called_once()
                args, _ = mock_queue.enqueue_in.call_args
                self.assertEqual(
                    args,
                    (
                        timedelta(seconds=settings.CACHE_EPOCH_SETTLE_SECONDS),
                        JobFn.RECLAIM_RETIRED_CACHE,
                        kind.value,
                        1,
                        "previous",
                    ),
                )

    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_cache_of_an_unknown_cache(self, mock_kc_auth):
        self._authorize_admin(mock_kc_auth)

        response = self.client.delete(
            "/admin/cache/compilation-cache", headers={"Authorization": "Bearer admin-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.UNPROCESSABLE_ENTITY)

    @patch("app.app.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_cache_unauthorized(self, mock_kc_auth, mock_logger):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "user-123",
            "preferred_username": "user",
            "email": "user@example.com",
        }
        mock_kc_auth.userinfo.return_value = {"groups": ["/other/group"]}

        response = self.client.delete(
            "/admin/cache/circuit", headers={"Authorization": "Bearer user-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.FORBIDDEN)


class TestStartCacheCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_the_reclaim_job_gets_the_cid_of_the_request(self):
        mock_queue = MagicMock()
        token = cid_var.set("request-cid")
        self.addCleanup(cid_var.reset, token)

        with (
            patch.dict(_queues, {JobQueue.MEDIUM: mock_queue}),
            patch.object(service, "rotate_epoch", return_value=None),
        ):
            await service.start_cache_cleanup(CacheKind.MESH, description="Mesh cache")

        _, kwargs = mock_queue.enqueue_in.call_args
        self.assertEqual(kwargs["meta"], {"cid": "request-cid"})


if __name__ == "__main__":
    unittest.main()
