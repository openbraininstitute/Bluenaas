import os
import unittest
from http import HTTPStatus
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from fastapi.testclient import TestClient

from app.app import app
from app.core.api import ApiResponse
from app.domains.neuron_model import CompatibilityCheckResponse


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")

AUTH_HEADERS = {
    "Authorization": "Bearer test-token",
    "project-id": "00000000-0000-0000-0000-000000000001",
    "virtual-lab-id": "00000000-0000-0000-0000-000000000002",
}


class TestCheckCompatibilityRoute(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("app.routes.single_neuron.check_compatibility_service")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_returns_200_with_compatible_result(self, mock_kc_auth, mock_service):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "user-123",
            "preferred_username": "user",
            "email": "user@example.com",
        }
        mock_kc_auth.userinfo.return_value = {"groups": []}

        mock_service.return_value = ApiResponse[CompatibilityCheckResponse](
            message="Compatibility check completed",
            data=CompatibilityCheckResponse(
                compatible=True,
                morphology_id=MORPH_ID,
                emodel_id=EMODEL_ID,
                error=None,
            ),
        )

        response = self.client.post(
            "/single-neuron/compatibility/run",
            json={
                "morphology_id": str(MORPH_ID),
                "emodel_id": str(EMODEL_ID),
            },
            headers=AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)

        body = response.json()
        self.assertEqual(body["message"], "Compatibility check completed")
        self.assertTrue(body["data"]["compatible"])
        self.assertEqual(body["data"]["morphology_id"], str(MORPH_ID))
        self.assertEqual(body["data"]["emodel_id"], str(EMODEL_ID))
        self.assertIsNone(body["data"]["error"])

    @patch("app.routes.single_neuron.check_compatibility_service")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_returns_200_with_incompatible_result(self, mock_kc_auth, mock_service):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "user-123",
            "preferred_username": "user",
            "email": "user@example.com",
        }
        mock_kc_auth.userinfo.return_value = {"groups": []}

        mock_service.return_value = ApiResponse[CompatibilityCheckResponse](
            message="Compatibility check completed",
            data=CompatibilityCheckResponse(
                compatible=False,
                morphology_id=MORPH_ID,
                emodel_id=EMODEL_ID,
                error="Single neuron model instantiation failed",
            ),
        )

        response = self.client.post(
            "/single-neuron/compatibility/run",
            json={
                "morphology_id": str(MORPH_ID),
                "emodel_id": str(EMODEL_ID),
            },
            headers=AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)

        body = response.json()
        self.assertFalse(body["data"]["compatible"])
        self.assertIsNotNone(body["data"]["error"])

    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_returns_422_with_invalid_body(self, mock_kc_auth):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "user-123",
            "preferred_username": "user",
            "email": "user@example.com",
        }
        mock_kc_auth.userinfo.return_value = {"groups": []}

        response = self.client.post(
            "/single-neuron/compatibility/run",
            json={"morphology_id": "not-a-uuid"},
            headers=AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, HTTPStatus.UNPROCESSABLE_ENTITY)


if __name__ == "__main__":
    unittest.main()
