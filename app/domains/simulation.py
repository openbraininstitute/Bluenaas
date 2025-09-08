from datetime import datetime
from typing import Annotated, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, PositiveFloat, field_validator

from app.domains.expandable_model import ExpandableModel, Scan


class SimulationStimulusConfig(ExpandableModel):
    stimulus_type: Literal["current_clamp", "voltage_clamp", "conductance"]
    stimulus_protocol: Optional[Literal["ap_waveform", "idrest", "iv", "fire_pattern"]]
    amplitudes: Scan[float]

    @field_validator("amplitudes")
    @classmethod
    def validate_amplitudes(cls, value):
        if isinstance(value, list):
            if len(value) < 1 or len(value) > 15:
                raise ValueError("Amplitude length should be between 1 and 15 (inclusive)")

        return value


class RecordingLocation(ExpandableModel):
    section: str
    offset: Annotated[float, Field(ge=0, le=1)]
    record_currents: bool = False


class CurrentInjectionConfig(ExpandableModel):
    inject_to: str
    stimulus: SimulationStimulusConfig


class ExperimentSetupConfig(ExpandableModel):
    celsius: float
    vinit: float
    hypamp: float
    max_time: Annotated[float, Field(le=3000)]
    time_step: float
    seed: int


NonNegativeFloat = Annotated[float, Field(ge=0)]


class SynapseSimulationConfig(ExpandableModel):
    id: str
    delay: int
    duration: Annotated[int, Field(le=3000)]
    frequency: Scan[NonNegativeFloat]
    weight_scalar: PositiveFloat


# class SimulationWithSynapseBody(ExpandableModel):
#     directCurrentConfig: CurrentInjectionConfig
#     synapseConfigs: list[SynapseSimulationConfig]


SimulationType = Literal["single-neuron-simulation", "synaptome-simulation"]


class SingleNeuronSimulationConfig(ExpandableModel):
    synaptome: list[SynapseSimulationConfig] | None = None
    current_injection: CurrentInjectionConfig
    record_from: list[RecordingLocation]
    conditions: ExperimentSetupConfig
    type: SimulationType
    duration: int


class StimulationPlotConfig(BaseModel):
    stimulus_protocol: Optional[Literal["ap_waveform", "idrest", "iv", "fire_pattern"]]
    amplitudes: List[float]


class SimulationItemResponse(BaseModel):
    t: List[float] = Field(..., description="Time points")
    v: List[float] = Field(..., description="Voltage points")
    name: str = Field(..., description="Name of the stimulus")


SimulationStatus = Literal["pending", "started", "success", "failure"]


class BrainRegion(BaseModel):
    id: str
    label: str


class SimulationDetailsResponse(BaseModel):
    id: str
    status: SimulationStatus | None = None
    results: Optional[dict]
    error: Optional[str]

    type: SimulationType
    name: str
    description: str
    created_by: str
    created_at: datetime
    injection_location: str
    recording_location: list[str] | str
    brain_region: BrainRegion
    config: Optional[SingleNeuronSimulationConfig]

    me_model_id: str
    synaptome_model_id: Optional[str]


class StimulationItemResponse(BaseModel):
    x: List[float]
    y: List[float]
    name: str
    amplitude: float


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    offset: int
    page_size: int
    total: int
    results: list[T]
