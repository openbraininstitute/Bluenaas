from uuid import UUID

from pydantic import BaseModel, Field

from entitysdk.models import CellMorphology


class SkeletonizationInputParams(BaseModel):
    name: str = Field(..., description="The name of the reconstructed morphology.")
    description: str = Field(..., description="A description of the reconstructed morphology.")


class SkeletonizationUltraliserParams(BaseModel):
    neuron_voxel_size: float | None = Field(
        0.1, description="Neuron skeletonization resolution (in microns)."
    )

    spines_voxel_size: float | None = Field(
        0.05, description="Spine skeletonization resolution (in microns)."
    )

    segment_spines: bool | None = Field(
        True, description="Set this flag to segment the spines or not."
    )


class SkeletonizationBatchRequest(BaseModel):
    config_ids: list[UUID] = Field(..., description="List of skeletonization config IDs to process")


class SkeletonizationJobOutput(BaseModel):
    morphology: CellMorphology
