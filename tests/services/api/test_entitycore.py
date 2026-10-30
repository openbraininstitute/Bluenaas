from http import HTTPStatus
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models import Circuit
from entitysdk.utils.http import HTTPStatusError

from app.core.exceptions import AppError
from app.services.api import entitycore as service


def _http_error(status: HTTPStatus) -> EntitySDKError:
    """The error entitysdk raises for an answer of `status`."""
    cause = HTTPStatusError("error", request=MagicMock(), response=MagicMock(status_code=status))
    try:
        raise EntitySDKError("HTTP error") from cause
    except EntitySDKError as error:
        return error


class TestGetEntityOrNotFound(TestCase):
    def get_with(self, error: EntitySDKError):
        with patch.object(service, "Client") as client:
            client.return_value.get_entity.side_effect = error
            return service.get_entity_or_not_found(
                uuid4(),
                Circuit,
                auth=MagicMock(),
                project_context=ProjectContext(project_id=uuid4(), virtual_lab_id=uuid4()),
                message="Circuit not found",
            )

    def test_an_entity_the_user_cannot_see_is_not_found(self):
        for status in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND]:
            with self.subTest(status=status):
                with self.assertRaises(AppError) as raised:
                    self.get_with(_http_error(status))

                self.assertEqual(raised.exception.http_status_code, HTTPStatus.NOT_FOUND)
                self.assertEqual(raised.exception.message, "Circuit not found")

    def test_other_errors_are_raised_as_they_are(self):
        with self.assertRaises(EntitySDKError):
            self.get_with(_http_error(HTTPStatus.BAD_GATEWAY))
