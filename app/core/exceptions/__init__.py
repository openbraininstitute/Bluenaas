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


class NotInitializedError(RuntimeError):
    pass


class AppErrorResponse(BaseModel):
    """The format of an error response"""

    error_code: AppErrorCode | None
    message: str | None = None
    details: str | None = None


class _BaseMessageException(Exception):
    """Base class for exceptions that only need a message.

    Subclasses supply their wording as ``default_message`` rather than redeclaring a
    constructor, so a new base-class field costs one edit instead of one per subclass.

    ``details`` carries the longer diagnostic behind the message — a captured NEURON
    log, a compiler transcript — for callers that want to surface or log it.
    """

    default_message = "Operation failed"

    def __init__(self, message: str | None = None, *, details: str | None = None) -> None:
        self.message = message or self.default_message
        self.details = details
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
    """NEURON refused the model itself — typically a morphology the emodel cannot use."""

    default_message = "Single neuron model instantiation failed"


class SingleNeuronAssetError(_BaseMessageException):
    """Model assets could not be fetched or compiled.

    Distinct from ``SingleNeuronInitError`` because it says nothing about whether the
    morphology and emodel go together — it is an infrastructure failure, and a caller
    should offer a retry rather than tell the user to pick a different combination.
    """

    default_message = "Single neuron model assets could not be prepared"


class EMCellMeshInitError(_BaseMessageException):
    def __init__(self, message: str = "EMCellMesh instantiation failed") -> None:
        super().__init__(message)


class IonChannelBuildError(_BaseMessageException):
    def __init__(self, message: str = "Ion channel build failed") -> None:
        super().__init__(message)
