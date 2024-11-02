from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

from bluenaas.domains.morphology import SynapseConfig

ModelType = Literal["me-model", "synaptome"]
NexusMEModelType = "MEModel"
NexusSynaptomeType = "SingleNeuronSynaptome"


class UsedModel(BaseModel):
    id: str
    type: ModelType
    name: str


class SynaptomeModelResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    type: ModelType
    created_by: str
    created_at: datetime

    me_model: UsedModel

    synapses: list[SynapseConfig]
