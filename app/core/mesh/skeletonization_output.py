from pathlib import Path
from typing import cast
from uuid import UUID
from loguru import logger
from pydantic import BaseModel

from entitysdk.client import Client
from entitysdk.models import ReconstructionMorphology, Species, BrainRegion
from entitysdk.models.asset import ContentType, AssetLabel

from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir


class Metadata(BaseModel):
    name: str
    description: str
    species: Species
    brain_region: BrainRegion


class SkeletonizationOutput:
    output_id: UUID
    path: Path
    client: Client
    metadata: Metadata

    def __init__(self, output_id: UUID, client: Client, metadata: Metadata) -> None:
        self.output_id = output_id
        self.client = client
        self.metadata = metadata
        self.path = get_mesh_skeletonization_output_location(self.output_id)

    def init(self) -> None:
        ensure_dir(self.path)

    def upload(self) -> ReconstructionMorphology:
        morph_path = next(self.path.rglob("*.swc"), None)

        if not morph_path:
            raise FileNotFoundError(f"No SWC file found in Ultraliser output location {self.path}")

        morphology = cast(
            ReconstructionMorphology,
            self.client.register_entity(
                ReconstructionMorphology(
                    name=self.metadata.name,
                    description=self.metadata.description,
                    species=self.metadata.species,
                    brain_region=self.metadata.brain_region,
                )
            ),
        )

        assert morphology.id

        self.client.upload_file(
            entity_id=morphology.id,
            entity_type=ReconstructionMorphology,
            file_path=morph_path,
            file_content_type=ContentType.application_swc,
            asset_label=AssetLabel.morphology,
        )

        return self.client.get_entity(morphology.id, entity_type=ReconstructionMorphology)

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        rm_dir(self.path)
