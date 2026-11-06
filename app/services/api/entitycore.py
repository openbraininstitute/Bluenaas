from http import HTTPStatus
from uuid import UUID

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models.core import Identifiable
from entitysdk.utils.http import HTTPClient, HTTPStatusError

from app.config.settings import settings
from app.core.exceptions import AppError


# Shared by every user's client, so that a request to entitycore reuses a connection
_http_client = HTTPClient()


def user_client(access_token: str, project_context: ProjectContext) -> Client:
    return Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        http_client=_http_client,
        token_manager=access_token,
    )


def get_entity_or_not_found[T: Identifiable](
    client: Client, entity_id: UUID, entity_type: type[T], *, message: str
) -> T:
    """The entity, as the client's user may see it. One the user can't see is not found."""
    try:
        return client.get_entity(entity_id, entity_type=entity_type)
    except EntitySDKError as ex:
        cause = ex.__cause__
        if isinstance(cause, HTTPStatusError) and cause.response.status_code in (
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
            HTTPStatus.NOT_FOUND,
        ):
            raise AppError(
                message=message, error_code=None, http_status_code=HTTPStatus.NOT_FOUND
            ) from ex
        raise
