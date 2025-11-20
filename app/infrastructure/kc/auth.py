from http import HTTPStatus as status

from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2AuthorizationCodeBearer,
)
from loguru import logger

from app.config.settings import settings
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
        # decoded_token_dict = kc_auth.decode_token(token=token, validate=True)
        decoded_token_dict = kc_auth.decode_token(token=access_token, validate=False)
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
