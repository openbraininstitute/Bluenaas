from typing import List, Optional

from pydantic import BaseModel, Field


class DecodedKeycloakToken(BaseModel):
    # JWT Standard Fields (RFC 7519)
    exp: int = Field(description="Expiration timestamp of the token")
    iat: Optional[int] = Field(description="Timestamp when the token was issued", default=None)
    jti: Optional[str] = Field(description="Unique identifier for the token", default=None)
    iss: str = Field(description="URL of the authentication server that issued the token")
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
    scope: Optional[str] = Field(description="Space-separated list of granted scopes", default=None)
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
    session_state: Optional[str] = Field(description="Keycloak's session identifier", default=None)
    acr: Optional[str] = Field(description="Authentication Context Class Reference", default=None)
    sid: Optional[str] = Field(description="Keycloak session ID", default=None)
    # * Add realm_access and resource_access fields if necessary.


class Auth(BaseModel):
    access_token: str
    decoded_token: DecodedKeycloakToken
