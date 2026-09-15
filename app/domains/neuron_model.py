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

    ``check_failed`` means a download, compilation or timeout stopped the check. Offer a
    retry for it, and ask for another combination only on ``incompatible``.
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
        """Derive ``status`` from ``compatible`` for payloads that predate it.

        They come from results cached before ``status`` existed, and from a worker on the
        previous image during a rolling deploy.
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
        """For clients that predate ``status``."""
        return self.status is CompatibilityStatus.compatible
