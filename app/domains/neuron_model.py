from enum import StrEnum, auto
from uuid import UUID
from pydantic import BaseModel, computed_field, model_validator
from typing import Any, Optional, Literal
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


class CompatibilityCheckRequest(BaseModel):
    morphology_id: UUID
    emodel_id: UUID


class CompatibilityStatus(StrEnum):
    """Outcome of a morphology + emodel compatibility check.

    ``check_failed`` is separate from ``incompatible``: a download, compilation or
    timeout failure says nothing about the models, so the caller should offer a retry
    instead of asking the user for another combination.
    """

    compatible = auto()
    incompatible = auto()
    check_failed = auto()


class CompatibilityCheckResponse(BaseModel):
    status: CompatibilityStatus
    morphology_id: UUID
    emodel_id: UUID
    error: str | None = None
    details: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_payload(cls, data: Any) -> Any:
        """Derive ``status`` from ``compatible`` when it is missing.

        Two producers predate ``status``: a cached result written to disk before it
        existed, and a worker still on the previous image during a rolling deploy.
        Without this the API rejects its own cache and its own worker's result.
        """
        if isinstance(data, dict) and "status" not in data and "compatible" in data:
            data = {
                **data,
                "status": (
                    CompatibilityStatus.compatible
                    if data["compatible"]
                    else CompatibilityStatus.incompatible
                ),
            }
        return data

    @computed_field
    @property
    def compatible(self) -> bool:
        """Kept for clients that predate ``status``; the two repos deploy independently."""
        return self.status is CompatibilityStatus.compatible
