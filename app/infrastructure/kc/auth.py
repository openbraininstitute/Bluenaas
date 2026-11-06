import json
import threading
import time
from http import HTTPStatus as status
from typing import Annotated

from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2AuthorizationCodeBearer,
)
from jwcrypto import jwk
from jwcrypto.common import base64url_decode, json_decode
from loguru import logger

from app.config.settings import settings
from app.constants import SERVICE_NAME
from app.core.exceptions import AppError, AppErrorCode
from app.domains.auth import Auth, DecodedKeycloakToken
from app.infrastructure.kc.config import kc_auth

auth_header: HTTPBearer | OAuth2AuthorizationCodeBearer = HTTPBearer(auto_error=False)

KC_SUBJECT: str = f"service-account-{settings.KC_CLIENT_ID}"

# How long Keycloak's signing keys are kept. A key it starts signing with is fetched when first seen.
SIGNING_KEYS_SECONDS = 10 * 60
# How often they are fetched again, at most: anyone can send a token of any key, and Keycloak may be
# down, when the keys held are used meanwhile
SIGNING_KEYS_REFRESH_SECONDS = 30


def _key_id(token: str) -> str | None:
    try:
        return json_decode(base64url_decode(token.split(".")[0])).get("kid")
    except Exception:
        return None


class SigningKeys:
    """Keycloak's keys that tokens are signed with, fetched once in a while rather than for every
    request.
    """

    def __init__(self):
        self._keys: jwk.JWKSet | None = None
        self._fetched_at = self._tried_at = 0.0
        self._lock = threading.Lock()

    def for_token(self, token: str) -> jwk.JWKSet:
        with self._lock:
            now = time.monotonic()
            if self._keys is not None and (
                now - self._tried_at <= SIGNING_KEYS_REFRESH_SECONDS
                or (now - self._fetched_at <= SIGNING_KEYS_SECONDS and not self._lacks(token))
            ):
                return self._keys
            self._tried_at = now
            try:
                keys = jwk.JWKSet()
                for cert in kc_auth.certs()["keys"]:
                    keys.add(jwk.JWK(**cert))
            except Exception as ex:
                if self._keys is None:
                    raise
                logger.warning(f"Keycloak's signing keys could not be fetched: {type(ex).__name__}")
                return self._keys
            self._keys, self._fetched_at = keys, now
            return keys

    def _lacks(self, token: str) -> bool:
        kid = _key_id(token)
        return kid is not None and self._keys is not None and not self._keys.get_key(kid)


signing_keys = SigningKeys()


def get_public_key() -> str:
    """
    get the public key to decode the token
    """
    return f"-----BEGIN PUBLIC KEY-----\n{kc_auth.public_key()}\n-----END PUBLIC KEY-----"


def verify_jwt(
    header: HTTPAuthorizationCredentials = Depends(auth_header),
) -> Auth:
    try:
        access_token = header.credentials
        decoded_token_dict = kc_auth.decode_token(
            token=access_token, validate=True, key=signing_keys.for_token(access_token)
        )
        decoded_token = DecodedKeycloakToken.model_validate(decoded_token_dict)
        return Auth(
            access_token=access_token,
            decoded_token=decoded_token,
        )
    except Exception as ex:
        logger.error(ex)
        raise AppError(
            message="The supplied authentication is not authorized to access",
            error_code=AppErrorCode.AUTHORIZATION_ERROR,
            http_status_code=status.UNAUTHORIZED,
        )


UserAuthDep = Annotated[Auth, Depends(verify_jwt)]


def verify_admin(auth: UserAuthDep) -> Auth:
    try:
        # Fetch user info from Keycloak which includes groups
        user_info_raw = kc_auth.userinfo(token=auth.access_token)

        # Handle both bytes and dict return types from python-keycloak
        if isinstance(user_info_raw, bytes):
            user_info = json.loads(user_info_raw)
        else:
            user_info = user_info_raw

        # Extract groups from userinfo
        group_paths = user_info.get("groups", [])

        required_groups = [
            f"/service/{SERVICE_NAME}/admin",
            "/service/*/admin",
        ]

        if not any(group in group_paths for group in required_groups):
            raise AppError(
                message="User is not authorized to access this resource",
                error_code=AppErrorCode.AUTHORIZATION_ERROR,
                http_status_code=status.FORBIDDEN,
            )

        auth.decoded_token.groups = group_paths
        return auth
    except AppError:
        raise
    except Exception as ex:
        logger.error(ex)
        raise AppError(
            message="Failed to verify admin authorization",
            error_code=AppErrorCode.AUTHORIZATION_ERROR,
            http_status_code=status.UNAUTHORIZED,
        )


AdminAuthDep = Annotated[Auth, Depends(verify_admin)]
