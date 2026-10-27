import os
import unittest
from http import HTTPStatus
from unittest.mock import MagicMock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from fastapi.testclient import TestClient

from app.app import app
from app.domains.auth import Auth, DecodedKeycloakToken
from app.infrastructure.rq import JobQueue, _queues
from app.job import JobFn


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
    def test_clear_cache_starts_a_cleanup_job_and_returns_immediately(self, mock_kc_auth):
        self._authorize_admin(mock_kc_auth)

        cases = [
            ("circuit", "circuit", "Circuit cache cleanup started"),
            ("single-neuron", "single-neuron", "Single neuron cache cleanup started"),
            ("mesh", "mesh", "Mesh cache cleanup started"),
            ("task-config", "task-config", "Task config cache cleanup started"),
            ("compilation", "compilation-cache", "Compilation cache cleanup started"),
        ]

        for endpoint, kind, message in cases:
            with self.subTest(endpoint=endpoint):
                mock_queue = MagicMock()
                mock_queue.enqueue.return_value.id = "job-1"

                with patch.dict(_queues, {JobQueue.MEDIUM: mock_queue}):
                    response = self.client.delete(
                        f"/admin/cache/{endpoint}", headers={"Authorization": "Bearer admin-token"}
                    )

                self.assertEqual(response.status_code, HTTPStatus.ACCEPTED)
                self.assertEqual(response.json(), {"message": message, "job_id": "job-1"})
                mock_queue.enqueue.assert_called_once()
                args, _ = mock_queue.enqueue.call_args
                self.assertEqual(args, (JobFn.CLEAR_CACHE, kind))

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


if __name__ == "__main__":
    unittest.main()
