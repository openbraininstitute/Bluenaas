from datetime import datetime
from typing import Annotated, Any, List, Optional, TypedDict
from pydantic import BaseModel, Field
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    PlotDataEntry,
    StimulationItemResponse,
)


class NexusBaseResource(BaseModel):
    context: Annotated[str | List[Any], Field(alias="@context")] = []
    id: Annotated[str, Field(alias="@id")]
    type: Annotated[str | List[str] | None, Field(alias="@type")] = None
    createdAt: Annotated[datetime, Field(alias="_createdAt")]
    createdBy: Annotated[str, Field(alias="_createdBy")]
    deprecated: Annotated[bool, Field(alias="_deprecated")]
    self: Annotated[str, Field(alias="_self")]
    rev: Annotated[int, Field(alias="_rev")]


NexusUsed = TypedDict(
    "NexusUsed",
    {
        "@type": list[str],
        "@id": str,
    },
)


class NexusSimulationPayload(BaseModel):
    config: SingleNeuronSimulationConfig
    simulation: Any
    stimulus: Optional[
        StimulationItemResponse
    ]  # TODO: Check if stimulus data should be saved in draft simulations


class NexusSimulationResource(BaseModel):
    type: Annotated[str | List[str], Field(alias="@type")]
    context: Annotated[str, Field(alias="@context")]
    name: str
    description: str
    used: NexusUsed
    distribution: list[dict[str, Any]]
    injectionLocation: str
    recordingLocation: list[str]
    brainLocation: Any  # TODO Add better type
    is_draft: bool
    status: str  # TODO Add better type

    class Config:
        populate_by_name = True
