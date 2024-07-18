from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SimulationStimulusConfig(BaseModel):
    stimulusType: Literal["current_clamp", "voltage_clamp", "conductance"]
    stimulusProtocol: Optional[Literal["ap_waveform", "idrest", "iv", "fire_pattern"]]
    paramValues: dict[str, Optional[float]]
    amplitudes: List[float]


class SimulationConfigBody(BaseModel):
    celsius: float
    hypamp: float
    vinit: float
    recordFrom: List[str]
    injectTo: str
    stimulus: SimulationStimulusConfig


class StimulationPlotConfig(BaseModel):
    stimulusProtocol: Optional[Literal["ap_waveform", "idrest", "iv", "fire_pattern"]]
    amplitudes: List[int]
    timestamp: int


class SimulationItemResponse(BaseModel):
    t: List[float] = Field(..., description="Time points")
    v: List[float] = Field(..., description="Voltage points")
    name: str = Field(..., description="Name of the stimulus")


class StimulationItemResponse(BaseModel):
    x: List[int]
    y: List[float]
    name: str
