from pathlib import Path
from typing import cast
from uuid import UUID
from loguru import logger

from entitysdk.client import Client
from entitysdk.models import ReconstructionMorphology
from entitysdk.models.asset import ContentType, AssetLabel

from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir


class SkeletonizationOutput:
    output_id: UUID
    path: Path
    client: Client

    def __init__(self, output_id: UUID, client: Client) -> None:
        self.output_id = output_id
        self.client = client
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
                    name="test",
                    description="test",
                    # subject
                    brain_region=None,
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

        return morphology

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        rm_dir(self.path)
