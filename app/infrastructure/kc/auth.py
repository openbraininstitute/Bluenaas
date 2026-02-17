import json
from http import HTTPStatus as status
from typing import Annotated

from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2AuthorizationCodeBearer,
)
from loguru import logger

from app.config.settings import settings
from app.constants import SERVICE_NAME
from app.core.exceptions import AppError, AppErrorCode
from app.domains.auth import Auth, DecodedKeycloakToken
from app.infrastructure.kc.config import kc_auth

auth_header: HTTPBearer | OAuth2AuthorizationCodeBearer = HTTPBearer(auto_error=False)

KC_SUBJECT: str = f"service-account-{settings.KC_CLIENT_ID}"


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
        decoded_token_dict = kc_auth.decode_token(token=access_token, validate=True)
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
