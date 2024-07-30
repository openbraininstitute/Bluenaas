from http import HTTPStatus as status

from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2AuthorizationCodeBearer,
)

from bluenaas.config.settings import settings
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.infrastructure.kc.config import kc_auth
from bluenaas.utils.bearer_token import token_to_bearer

auth_header: HTTPBearer | OAuth2AuthorizationCodeBearer = HTTPBearer(auto_error=False)

KC_SUBJECT: str = f"service-account-{settings.KC_CLIENT_ID}"


def get_public_key() -> str:
    """
    get the public key to decode the token
    """
    return (
        f"-----BEGIN PUBLIC KEY-----\n{kc_auth.public_key()}\n-----END PUBLIC KEY-----"
    )


def verify_jwt(
    header: HTTPAuthorizationCredentials = Depends(auth_header),
) -> str:
    try:
        token = header.credentials
        kc_auth.decode_token(token=token, validate=True)
        return token_to_bearer(token)
    except Exception:
        raise BlueNaasError(
            message="The supplied authentication is not authorized to access",
            error_code=BlueNaasErrorCode.AUTHORIZATION_ERROR,
            http_status_code=status.UNAUTHORIZED,
        )
