from http import HTTPStatus
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx2
from entitysdk.exception import EntitySDKError
from entitysdk.models import Circuit
from entitysdk.utils.http import HTTPStatusError

from app.core.exceptions import AppError
from app.services.api import entitycore
from app.services.api.entitycore import get_entity_or_not_found


def _http_error(status: HTTPStatus) -> EntitySDKError:
    """The error entitysdk raises for an answer of `status`."""
    cause = HTTPStatusError("error", request=MagicMock(), response=MagicMock(status_code=status))
    try:
        raise EntitySDKError("HTTP error") from cause
    except EntitySDKError as error:
        return error


class TestGetEntityOrNotFound(TestCase):
    def get_with(self, error: EntitySDKError):
        client = MagicMock()
        client.get_entity.side_effect = error
        return get_entity_or_not_found(client, uuid4(), Circuit, message="Circuit not found")

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


class TestSharedHttpClient(TestCase):
    def test_a_cookie_set_for_one_user_is_not_sent_with_another_users_request(self):
        sent = []

        def answer(request):
            sent.append(request.headers.get("cookie"))
            return httpx2.Response(200, headers={"set-cookie": "AWSALB=abc; Path=/"})

        client = entitycore._http_client
        with patch.object(client, "_transport", httpx2.MockTransport(answer)):
            client.get("https://entitycore.test/a", headers={"authorization": "Bearer a"})
            client.get("https://entitycore.test/b", headers={"authorization": "Bearer b"})

        self.assertEqual(sent, [None, None])
