from http import HTTPStatus as status
from typing import List, Optional

from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2AuthorizationCodeBearer,
)
from loguru import logger
from pydantic import BaseModel, Field

from bluenaas.config.settings import settings
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.infrastructure.kc.config import kc_auth
from bluenaas.utils.bearer_token import token_to_bearer

auth_header: HTTPBearer | OAuth2AuthorizationCodeBearer = HTTPBearer(auto_error=False)

KC_SUBJECT: str = f"service-account-{settings.KC_CLIENT_ID}"


class DecodedKeycloakToken(BaseModel):
    # JWT Standard Fields (RFC 7519)
    exp: int = Field(description="Expiration timestamp of the token")
    iat: Optional[int] = Field(
        description="Timestamp when the token was issued", default=None
    )
    jti: Optional[str] = Field(
        description="Unique identifier for the token", default=None
    )
    iss: str = Field(
        description="URL of the authentication server that issued the token"
    )
    sub: str = Field(description="Unique identifier for the user")
    aud: Optional[List[str] | str] = Field(
        description="Intended recipient of the token", default=None
    )

    # OIDC Standard Fields
    typ: Optional[str] = Field(description="Token type, usually 'Bearer'", default=None)
    azp: Optional[str] = Field(
        description="Authorized party - the client that requested the token",
        default=None,
    )
    scope: Optional[str] = Field(
        description="Space-separated list of granted scopes", default=None
    )
    email_verified: Optional[bool] = Field(
        description="Indicates if the user's email is verified", default=None
    )
    name: Optional[str] = Field(description="Full name of the user", default=None)
    preferred_username: str = Field(description="User's preferred username")
    given_name: Optional[str] = Field(description="User's first name", default=None)
    family_name: Optional[str] = Field(description="User's last name", default=None)
    email: str = Field(description="User's email address")

    # Keycloak-Specific Fields
    auth_time: Optional[int] = Field(
        description="Timestamp of the original authentication", default=None
    )
    session_state: Optional[str] = Field(
        description="Keycloak's session identifier", default=None
    )
    acr: Optional[str] = Field(
        description="Authentication Context Class Reference", default=None
    )
    sid: Optional[str] = Field(description="Keycloak session ID", default=None)
    # * Add realm_access and resource_access fields if necessary.


class Auth(BaseModel):
    token: str
    # decoded_token: DecodedKeycloakToken


def get_public_key() -> str:
    """
    get the public key to decode the token
    """
    return (
        f"-----BEGIN PUBLIC KEY-----\n{kc_auth.public_key()}\n-----END PUBLIC KEY-----"
    )


def verify_jwt(
    header: HTTPAuthorizationCredentials = Depends(auth_header),
) -> Auth:
    try:
        token = header.credentials
        #decoded_token_dict = kc_auth.decode_token(token=token, validate=True)
        #decoded_token = DecodedKeycloakToken.model_validate(decoded_token_dict)
        return Auth(
            token=token_to_bearer(token),
            # decoded_token=decoded_token,
        )
    except Exception as ex:
        logger.error(ex)
        raise BlueNaasError(
            message="The supplied authentication is not authorized to access",
            error_code=BlueNaasErrorCode.AUTHORIZATION_ERROR,
            http_status_code=status.UNAUTHORIZED,
        )
