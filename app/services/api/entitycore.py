from http import HTTPStatus
from uuid import UUID

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models.core import Identifiable
from entitysdk.utils.http import HTTPStatusError

from app.config.settings import settings
from app.core.exceptions import AppError
from app.infrastructure.kc.auth import Auth


def get_entity_or_not_found[T: Identifiable](
    entity_id: UUID,
    entity_type: type[T],
    *,
    auth: Auth,
    project_context: ProjectContext,
    message: str,
) -> T:
    """The entity, as the user may see it. One the user can't see is not found."""
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )
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
