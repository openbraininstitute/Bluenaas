from pathlib import Path
from typing import cast
from uuid import UUID

from entitysdk.client import Client
from entitysdk.models import BrainRegion, CellMorphology, Contribution, License, Role
from entitysdk.models.asset import AssetLabel, ContentType
from loguru import logger
from pydantic import BaseModel

from app.constants import SKELETONIZATION_OUTPUT_LICENSE_LABEL, SKELETONIZATION_OUTPUT_ROLE_NAME
from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir


class Metadata(BaseModel):
    name: str
    description: str
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

    def upload(self) -> CellMorphology:
        morph_path = next(self.path.rglob("*.swc"), None)

        if not morph_path:
            raise FileNotFoundError(f"No SWC file found in Ultraliser output location {self.path}")

        # TODO: Add query by label when supported in entitycore
        licenses = cast(list[License], self.client.search_entity(entity_type=License))
        license = next(
            filter(lambda license: license.label == SKELETONIZATION_OUTPUT_LICENSE_LABEL, licenses),
            None,
        )
        if not license:
            raise ValueError(f"License {SKELETONIZATION_OUTPUT_LICENSE_LABEL} not found")

        # TODO: Add query by name when supported in entitycore
        roles = cast(list[Role], self.client.search_entity(entity_type=Role))
        role = next(filter(lambda role: role.name == SKELETONIZATION_OUTPUT_ROLE_NAME, roles), None)
        if not role:
            raise ValueError(f"Role {SKELETONIZATION_OUTPUT_ROLE_NAME} not found")

        morphology = cast(
            CellMorphology,
            self.client.register_entity(
                CellMorphology(
                    name=self.metadata.name,
                    description=self.metadata.description,
                    brain_region=self.metadata.brain_region,
                    license=license,
                )
            ),
        )

        assert morphology.id
        assert morphology.created_by

        self.client.register_entity(
            Contribution(
                entity=morphology,
                role=role,
                agent=morphology.created_by,
            )
        )

        self.client.upload_file(
            entity_id=morphology.id,
            entity_type=CellMorphology,
            file_path=morph_path,
            file_content_type=ContentType.application_swc,
            asset_label=AssetLabel.morphology,
        )

        return self.client.get_entity(morphology.id, entity_type=CellMorphology)

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        logger.info(f"Cleaning up skeletonization output {self.path}")
        rm_dir(self.path)
