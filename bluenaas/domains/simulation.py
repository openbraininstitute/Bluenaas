from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, Field, PositiveInt


class SimulationStimulusConfig(BaseModel):
    stimulusType: Literal["current_clamp", "voltage_clamp", "conductance"]
    stimulusProtocol: Optional[Literal["ap_waveform", "idrest", "iv", "fire_pattern"]]
    paramValues: dict[str, Optional[float]]
    amplitudes: List[float]


class RecordingLocation(BaseModel):
    section: str
    segment_offset: Annotated[float, Field(ge=0, le=1, alias="segmentOffset")]


class DirectCurrentConfig(BaseModel):
    celsius: float
    hypamp: float
    vinit: float
    recordFrom: list[RecordingLocation]
    injectTo: str
    stimulus: SimulationStimulusConfig


class SynapseSimulationConfig(BaseModel):
    id: str
    delay: int
    duration: int
    frequency: PositiveInt
    weightScalar: int


class SimulationWithSynapseBody(BaseModel):
    directCurrentConfig: DirectCurrentConfig
    synapseConfigs: list[SynapseSimulationConfig]


class StimulationPlotConfig(BaseModel):
    stimulusProtocol: Optional[Literal["ap_waveform", "idrest", "iv", "fire_pattern"]]
    amplitudes: List[int]


class SimulationItemResponse(BaseModel):
    t: List[float] = Field(..., description="Time points")
    v: List[float] = Field(..., description="Voltage points")
    name: str = Field(..., description="Name of the stimulus")


class StimulationItemResponse(BaseModel):
    x: List[int]
    y: List[float]
    name: str
