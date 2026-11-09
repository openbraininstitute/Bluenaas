import json
import os
import unittest
from http import HTTPStatus
from unittest.mock import ANY, Mock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from jwcrypto import jwk
from jwcrypto.common import base64url_encode, json_encode

from app.core.exceptions import AppError
from app.domains.auth import Auth, DecodedKeycloakToken
from app.infrastructure.kc import auth
from app.infrastructure.kc.auth import (
    SIGNING_KEYS_REFRESH_SECONDS,
    SIGNING_KEYS_SECONDS,
    SigningKeys,
    verify_admin,
    verify_jwt,
)


def key_of(kid: str) -> dict:
    return json.loads(jwk.JWK.generate(kty="oct", size=256, kid=kid).export())


def token_of(kid: str) -> str:
    return f"{base64url_encode(json_encode({'alg': 'HS256', 'kid': kid}))}.e30.sig"


class TestSigningKeys(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(auth, "kc_auth")
        self.kc_auth = patcher.start()
        self.addCleanup(patcher.stop)
        self.kc_auth.certs.return_value = {"keys": [key_of("a")]}
        self.now = 1000.0
        patcher = patch.object(auth.time, "monotonic", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.keys = SigningKeys()

    def test_fetched_once_for_many_tokens(self):
        for _ in range(5):
            keys = self.keys.for_token(token_of("a"))

        self.assertEqual(self.kc_auth.certs.call_count, 1)
        self.assertIsNotNone(keys.get_key("a"))

    def test_fetched_again_once_they_are_old(self):
        self.keys.for_token(token_of("a"))

        self.now += SIGNING_KEYS_SECONDS + 1
        self.keys.for_token(token_of("a"))

        self.assertEqual(self.kc_auth.certs.call_count, 2)

    def test_a_new_key_is_fetched_when_first_seen_but_not_for_every_token(self):
        self.keys.for_token(token_of("a"))
        self.now += SIGNING_KEYS_REFRESH_SECONDS + 1
        self.kc_auth.certs.return_value = {"keys": [key_of("a"), key_of("b")]}

        keys = self.keys.for_token(token_of("b"))
        for _ in range(5):
            self.keys.for_token(token_of("c"))

        self.assertIsNotNone(keys.get_key("b"))
        self.assertEqual(self.kc_auth.certs.call_count, 2)

    def test_the_keys_held_are_used_while_keycloak_can_not_give_them(self):
        held = self.keys.for_token(token_of("a"))
        self.now += SIGNING_KEYS_SECONDS + 1
        self.kc_auth.certs.side_effect = ConnectionError("down")

        for _ in range(5):
            self.assertIs(self.keys.for_token(token_of("a")), held)

        self.assertEqual(self.kc_auth.certs.call_count, 2)
        self.now += SIGNING_KEYS_REFRESH_SECONDS + 1
        self.kc_auth.certs.side_effect = None
        self.assertIsNot(self.keys.for_token(token_of("a")), held)

    def test_no_keys_to_use_is_a_failure(self):
        self.kc_auth.certs.side_effect = ConnectionError("down")

        with self.assertRaises(ConnectionError):
            self.keys.for_token(token_of("a"))

    def test_a_token_that_is_no_jwt_is_left_to_fail_its_decoding(self):
        self.keys.for_token("not a token")

        self.assertEqual(self.kc_auth.certs.call_count, 1)


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
        mock_kc_auth.decode_token.assert_called_once_with(
            token="valid-token", validate=True, key=ANY
        )

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
