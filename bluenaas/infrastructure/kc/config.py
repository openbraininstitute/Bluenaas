from keycloak import KeycloakAdmin, KeycloakOpenID

from bluenaas.config.settings import settings

kc_realm = KeycloakAdmin(
    server_url=settings.KC_SERVER_URI,
    client_id=settings.KC_CLIENT_ID,
    client_secret_key=settings.KC_CLIENT_SECRET,
    realm_name=settings.KC_REALM_NAME,
)

kc_auth = KeycloakOpenID(
    client_id=settings.KC_CLIENT_ID,
    client_secret_key=settings.KC_CLIENT_SECRET,
    realm_name=settings.KC_REALM_NAME,
    server_url=settings.KC_SERVER_URI,
    verify=True,
)
