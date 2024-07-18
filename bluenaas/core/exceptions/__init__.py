from enum import StrEnum
from http import HTTPStatus

from pydantic import BaseModel


class BlueNaasErrorCode(StrEnum):
    """
    Error codes of the blue naas service
    """

    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class BlueNaasError(Exception):
    """Base class for blue naas service exceptions."""

    message: str
    error_code: str | None
    http_status_code: HTTPStatus
    details: str | None

    def __init__(
        self,
        *,
        message: str,
        error_code: BlueNaasErrorCode | None,
        details: str | None = None,
        http_status_code: HTTPStatus = HTTPStatus.BAD_REQUEST,
    ):
        super().__init__(message, error_code, http_status_code)
        self.message = message
        self.error_code = error_code
        self.http_status_code = http_status_code
        self.details = details

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f'{class_name}(message="{self.message}", error_code={self.error_code}, details={self.details}, http_status_code={self.http_status_code})'


class BlueNaasErrorResponse(BaseModel):
    """The format of an error response"""

    error_code: BlueNaasErrorCode | None
    message: str | None = None
    details: str | None = None
