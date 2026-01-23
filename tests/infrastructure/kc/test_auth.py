import os
import unittest
from http import HTTPStatus
from unittest.mock import Mock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.exceptions import AppError
from app.domains.auth import Auth, DecodedKeycloakToken
from app.infrastructure.kc.auth import verify_admin, verify_jwt


class TestVerifyJWT(unittest.TestCase):
    @patch("app.infrastructure.kc.auth.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_verify_jwt_valid_token(self, mock_kc_auth, mock_logger):
        mock_kc_auth.decode_token.return_value = {
            "exp": 1234567890,
            "iss": "http://localhost:9090/",
            "sub": "user-123",
            "preferred_username": "testuser",
            "email": "test@example.com",
        }

        mock_header = Mock()
        mock_header.credentials = "valid-token"

        result = verify_jwt(mock_header)

        self.assertIsInstance(result, Auth)
        self.assertEqual(result.access_token, "valid-token")
        self.assertEqual(result.decoded_token.sub, "user-123")
        self.assertEqual(result.decoded_token.email, "test@example.com")
        mock_kc_auth.decode_token.assert_called_once_with(token="valid-token", validate=True)

    @patch("app.infrastructure.kc.auth.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_verify_jwt_invalid_token(self, mock_kc_auth, mock_logger):
        mock_kc_auth.decode_token.side_effect = Exception("Invalid token")

        mock_header = Mock()
        mock_header.credentials = "invalid-token"

        with self.assertRaises(AppError) as context:
            verify_jwt(mock_header)

        self.assertEqual(context.exception.http_status_code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(
            context.exception.message, "The supplied authentication is not authorized to access"
        )


class TestVerifyAdmin(unittest.TestCase):
    @patch("app.infrastructure.kc.auth.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_verify_admin_with_service_specific_group(self, mock_kc_auth, mock_logger):
        mock_kc_auth.userinfo.return_value = {
            "groups": [
                "/service/small-scale-simulator/admin",
                "/other/group",
            ]
        }

        auth = Auth(
            access_token="token",
            decoded_token=DecodedKeycloakToken(
                exp=1234567890,
                iss="http://localhost:9090/",
                sub="user-123",
                preferred_username="testuser",
                email="test@example.com",
            ),
        )

        result = verify_admin(auth)

        self.assertIsInstance(result, Auth)
        self.assertIsNotNone(result.decoded_token.groups)
        self.assertIn("/service/small-scale-simulator/admin", result.decoded_token.groups)
        mock_kc_auth.userinfo.assert_called_once_with(token="token")

    @patch("app.infrastructure.kc.auth.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_verify_admin_with_wildcard_group(self, mock_kc_auth, mock_logger):
        mock_kc_auth.userinfo.return_value = {
            "groups": [
                "/service/*/admin",
                "/other/group",
            ]
        }

        auth = Auth(
            access_token="token",
            decoded_token=DecodedKeycloakToken(
                exp=1234567890,
                iss="http://localhost:9090/",
                sub="user-123",
                preferred_username="testuser",
                email="test@example.com",
            ),
        )

        result = verify_admin(auth)

        self.assertIsInstance(result, Auth)
        self.assertIsNotNone(result.decoded_token.groups)
        self.assertIn("/service/*/admin", result.decoded_token.groups)

    @patch("app.infrastructure.kc.auth.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_verify_admin_without_admin_group(self, mock_kc_auth, mock_logger):
        mock_kc_auth.userinfo.return_value = {
            "groups": [
                "/other/group",
                "/service/other-service/admin",
            ]
        }

        auth = Auth(
            access_token="token",
            decoded_token=DecodedKeycloakToken(
                exp=1234567890,
                iss="http://localhost:9090/",
                sub="user-123",
                preferred_username="testuser",
                email="test@example.com",
            ),
        )

        with self.assertRaises(AppError) as context:
            verify_admin(auth)

        self.assertEqual(context.exception.http_status_code, HTTPStatus.FORBIDDEN)
        self.assertEqual(
            context.exception.message, "User is not authorized to access this resource"
        )

    @patch("app.infrastructure.kc.auth.logger")
    @patch("app.infrastructure.kc.auth.kc_auth")
    def test_verify_admin_keycloak_error(self, mock_kc_auth, mock_logger):
        mock_kc_auth.userinfo.side_effect = Exception("Keycloak error")

        auth = Auth(
            access_token="token",
            decoded_token=DecodedKeycloakToken(
                exp=1234567890,
                iss="http://localhost:9090/",
                sub="user-123",
                preferred_username="testuser",
                email="test@example.com",
            ),
        )

        with self.assertRaises(AppError) as context:
            verify_admin(auth)

        self.assertEqual(context.exception.http_status_code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(context.exception.message, "Failed to verify admin authorization")


if __name__ == "__main__":
    unittest.main()
