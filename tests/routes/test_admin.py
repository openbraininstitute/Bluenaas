import os
import unittest
from http import HTTPStatus
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from fastapi.testclient import TestClient

from app.app import app
from app.domains.auth import Auth, DecodedKeycloakToken


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

    @patch("app.routes.admin.clear_circuit_cache")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_circuit_cache_success(self, mock_kc_auth, mock_clear_cache):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "admin-123",
            "preferred_username": "admin",
            "email": "admin@example.com",
        }
        mock_kc_auth.userinfo.return_value = {
            "groups": ["/service/small-scale-simulator/admin"]
        }

        response = self.client.delete(
            "/admin/cache/circuit", headers={"Authorization": "Bearer admin-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json(), {"message": "Circuit cache cleared successfully"})
        mock_clear_cache.assert_called_once()

    @patch("app.routes.admin.clear_single_neuron_cache")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_single_neuron_cache_success(self, mock_kc_auth, mock_clear_cache):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "admin-123",
            "preferred_username": "admin",
            "email": "admin@example.com",
        }
        mock_kc_auth.userinfo.return_value = {
            "groups": ["/service/small-scale-simulator/admin"]
        }

        response = self.client.delete(
            "/admin/cache/single-neuron", headers={"Authorization": "Bearer admin-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json(), {"message": "Single neuron cache cleared successfully"})
        mock_clear_cache.assert_called_once()

    @patch("app.routes.admin.clear_mesh_cache")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_mesh_cache_success(self, mock_kc_auth, mock_clear_cache):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "admin-123",
            "preferred_username": "admin",
            "email": "admin@example.com",
        }
        mock_kc_auth.userinfo.return_value = {
            "groups": ["/service/small-scale-simulator/admin"]
        }

        response = self.client.delete(
            "/admin/cache/mesh", headers={"Authorization": "Bearer admin-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json(), {"message": "Mesh cache cleared successfully"})
        mock_clear_cache.assert_called_once()

    @patch("app.routes.admin.clear_ion_channel_cache")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_clear_ion_channel_cache_success(self, mock_kc_auth, mock_clear_cache):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "admin-123",
            "preferred_username": "admin",
            "email": "admin@example.com",
        }
        mock_kc_auth.userinfo.return_value = {
            "groups": ["/service/small-scale-simulator/admin"]
        }

        response = self.client.delete(
            "/admin/cache/ion-channel", headers={"Authorization": "Bearer admin-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json(), {"message": "Ion channel cache cleared successfully"})
        mock_clear_cache.assert_called_once()

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
