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
    """``details`` holds the output behind the message, such as NEURON's or nrnivmodl's."""

    default_message = "Operation failed"

    def __init__(self, message: str | None = None, *, details: str | None = None) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class SimulationError(_BaseMessageException):
    default_message = "Simulation failed"


class SingleNeuronSynaptomeConfigurationError(_BaseMessageException):
    default_message = "Configuration not found"


class ChildSimulationError(_BaseMessageException):
    default_message = "Child simulation failed"


class SynapseGenerationError(_BaseMessageException):
    default_message = "Synapse generation failed"


class MorphologyGenerationError(_BaseMessageException):
    default_message = "Morphology generation failed"


class StimulationPlotGenerationError(_BaseMessageException):
    default_message = "Stimulation plot generation failed"


class CircuitInitError(_BaseMessageException):
    default_message = "Circuit instantiation failed"


class CircuitSimulationInitError(_BaseMessageException):
    default_message = "Circuit simulation instantiation failed"


class CircuitSimulationError(_BaseMessageException):
    default_message = "Circuit simulation failed"


class SingleNeuronInitError(_BaseMessageException):
    """NEURON rejected the model, usually a morphology the emodel cannot use."""

    default_message = "Single neuron model instantiation failed"


class SingleNeuronAssetError(_BaseMessageException):
    """Fetching or compiling the model assets failed."""

    default_message = "Single neuron model assets could not be prepared"


class EMCellMeshInitError(_BaseMessageException):
    default_message = "EMCellMesh instantiation failed"


class IonChannelBuildError(_BaseMessageException):
    default_message = "Ion channel build failed"
