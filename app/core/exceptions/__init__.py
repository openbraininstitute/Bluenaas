from enum import StrEnum
from http import HTTPStatus

from pydantic import BaseModel


class AppErrorCode(StrEnum):
    """
    Error codes of the blue naas service
    """

    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    UNKNOWN_BLUENAAS_ERROR = "UNKNOWN_BLUENAAS_ERROR"
    SYNAPSE_PLACEMENT_ERROR = "SYNAPSE_PLACEMENT_ERROR"
    SIMULATION_ERROR = "SIMULATION_ERROR"
    MORPHOLOGY_GENERATION_ERROR = "MORPHOLOGY_GENERATION_ERROR"
    ACCOUNTING_INSUFFICIENT_FUNDS_ERROR = "ACCOUNTING_INSUFFICIENT_FUNDS_ERROR"
    ACCOUNTING_GENERIC_ERROR = "ACCOUNTING_GENERIC_ERROR"


class AppError(Exception):
    """Base class for blue naas service exceptions."""

    message: str
    error_code: str | None
    http_status_code: HTTPStatus
    details: str | None

    def __init__(
        self,
        *,
        message: str,
        error_code: AppErrorCode | None,
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


class AppErrorResponse(BaseModel):
    """The format of an error response"""

    error_code: AppErrorCode | None
    message: str | None = None
    details: str | None = None


class _BaseMessageException(Exception):
    """Base class for exceptions that only need a message."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class SimulationError(_BaseMessageException):
    def __init__(self, message: str = "Simulation failed") -> None:
        super().__init__(message)


class SingleNeuronSynaptomeConfigurationError(_BaseMessageException):
    def __init__(self, message: str = "Configuration not found") -> None:
        super().__init__(message)


class ChildSimulationError(_BaseMessageException):
    def __init__(self, message: str = "Child simulation failed") -> None:
        super().__init__(message)


class SynapseGenerationError(_BaseMessageException):
    def __init__(self, message: str = "Synapse generation failed") -> None:
        super().__init__(message)


class MorphologyGenerationError(_BaseMessageException):
    def __init__(self, message: str = "Morphology generation failed") -> None:
        super().__init__(message)


class StimulationPlotGenerationError(_BaseMessageException):
    def __init__(self, message: str = "Stimulation plot generation failed") -> None:
        super().__init__(message)


class CircuitInitError(_BaseMessageException):
    def __init__(self, message: str = "Circuit instantiation failed") -> None:
        super().__init__(message)


class CircuitSimulationInitError(_BaseMessageException):
    def __init__(self, message: str = "Circuit simulation instantiation failed") -> None:
        super().__init__(message)


class CircuitSimulationError(_BaseMessageException):
    def __init__(self, message: str = "Circuit simulation failed") -> None:
        super().__init__(message)


class SingleNeuronInitError(_BaseMessageException):
    def __init__(self, message: str = "Single neuron model instantiation failed") -> None:
        super().__init__(message)
