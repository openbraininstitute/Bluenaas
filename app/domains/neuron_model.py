from uuid import UUID
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

from app.domains.morphology import SynapseConfig
from app.domains.simulation import BrainRegion

ModelType = Literal["me-model", "synaptome", "m-model", "e-model"]


class UsedModel(BaseModel):
    id: str
    type: ModelType
    name: str


class SynaptomeConfiguration(BaseModel):
    synapses: list[SynapseConfig]


class SynaptomeModelResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    type: ModelType
    created_by: str
    created_at: datetime

    brain_region: BrainRegion
    me_model: UsedModel

    synapses: list[SynapseConfig]


class MEModelResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    type: ModelType
    created_by: str
    created_at: datetime

    brain_region: BrainRegion
    m_model: UsedModel
    e_model: UsedModel


class MEModelCreateRequest(BaseModel):
    name: str
    description: str
    emodel_id: UUID
    morphology_id: UUID
    species_id: UUID
    brain_region_id: UUID
    strain_id: UUID | None = None


class SingleNeuronSynaptomeCreateRequest(BaseModel):
    name: str
    description: str
    memodel_id: UUID
    brain_region_id: UUID
    seed: int
    config: SynaptomeConfiguration
