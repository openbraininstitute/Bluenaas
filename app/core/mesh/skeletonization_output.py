from pathlib import Path
from typing import cast
from uuid import UUID

from morphio import Morphology
from entitysdk.client import Client
from entitysdk.models import BrainRegion, CellMorphology, Contribution, License, Role, Subject
from entitysdk.models.asset import AssetLabel, ContentType
from loguru import logger
from pydantic import BaseModel

from app.constants import SKELETONIZATION_OUTPUT_LICENSE_LABEL, SKELETONIZATION_OUTPUT_ROLE_NAME
from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir


SPINY_MORPH_PATH_SUFFIX = "_with_spines"


class Metadata(BaseModel):
    name: str
    description: str
    brain_region: BrainRegion
    subject: Subject


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
        logger.debug(f"Initialized skeletonization output folder {self.path}")

    def post_process(self) -> None:
        spiny_morph_path = next(self.path.rglob("*.h5"), None)
        assert spiny_morph_path, "No combined morphology file found in the output location"

        # Rename the combined morphology by adding "_with_spines" suffix
        spiny_morph_path.rename(
            spiny_morph_path.with_name(
                spiny_morph_path.stem + SPINY_MORPH_PATH_SUFFIX + spiny_morph_path.suffix
            )
        )

        morph_path = next(self.path.rglob("*.swc"), None)
        assert morph_path, "No SWC morphology file found in the output location"

        # Produce complimentary H5 and ASC morphologies from the original SWC
        morpho = Morphology(str(morph_path))
        h5_path = morph_path.with_name(morph_path.stem + ".h5")
        asc_path = morph_path.with_name(morph_path.stem + ".asc")

        morpho.write(str(h5_path))
        morpho.write(str(asc_path))

    def upload(self) -> CellMorphology:
        swc_morph_path = next(self.path.rglob("*.swc"), None)
        assert swc_morph_path, "No SWC morphology file found in the output location"

        h5_morph_path = swc_morph_path.with_name(swc_morph_path.stem + ".h5")
        assert h5_morph_path.exists(), (
            f"No smooth H5 morphology file found in the output location: {h5_morph_path}"
        )

        asc_morph_path = swc_morph_path.with_name(swc_morph_path.stem + ".asc")
        assert asc_morph_path.exists(), (
            f"No ASC morphology file found in the output location: {asc_morph_path}"
        )

        spiny_morph_path = next(self.path.rglob(f"*{SPINY_MORPH_PATH_SUFFIX}.h5"), None)
        assert spiny_morph_path, (
            f"No spiny H5 morphology file found in the output location: {spiny_morph_path}"
        )

        # TODO: Add query by label when supported in entitycore
        licenses = cast(list[License], self.client.search_entity(entity_type=License))
        license = next(
            filter(lambda license: license.label == SKELETONIZATION_OUTPUT_LICENSE_LABEL, licenses),
            None,
        )
        if not license:
            raise ValueError(f"License {SKELETONIZATION_OUTPUT_LICENSE_LABEL} not found")

        logger.debug(f"Using license: {license}")

        # TODO: Add query by name when supported in entitycore
        roles = cast(list[Role], self.client.search_entity(entity_type=Role))
        role = next(filter(lambda role: role.name == SKELETONIZATION_OUTPUT_ROLE_NAME, roles), None)
        if not role:
            raise ValueError(f"Role {SKELETONIZATION_OUTPUT_ROLE_NAME} not found")

        logger.debug(f"Using role: {role}")

        morphology = cast(
            CellMorphology,
            self.client.register_entity(
                CellMorphology(
                    name=self.metadata.name,
                    description=self.metadata.description,
                    brain_region=self.metadata.brain_region,
                    subject=self.metadata.subject,
                    license=license,
                )
            ),
        )

        assert morphology.id
        assert morphology.created_by

        contribution = self.client.register_entity(
            Contribution(
                entity=morphology,
                role=role,
                agent=morphology.created_by,
            )
        )

        logger.debug(f"Created contribution: {contribution}")

        self.client.upload_file(
            entity_id=morphology.id,
            entity_type=CellMorphology,
            file_path=swc_morph_path,
            file_content_type=ContentType.application_swc,
            asset_label=AssetLabel.morphology,
        )

        self.client.upload_file(
            entity_id=morphology.id,
            entity_type=CellMorphology,
            file_path=asc_morph_path,
            file_content_type=ContentType.application_asc,
            asset_label=AssetLabel.morphology,
        )

        self.client.upload_file(
            entity_id=morphology.id,
            entity_type=CellMorphology,
            file_path=h5_morph_path,
            file_content_type=ContentType.application_x_hdf5,
            asset_label=AssetLabel.morphology,
        )

        self.client.upload_file(
            entity_id=morphology.id,
            entity_type=CellMorphology,
            file_path=spiny_morph_path,
            file_content_type=ContentType.application_x_hdf5,
            asset_label=AssetLabel.morphology_with_spines,
        )

        logger.debug(f"Upload complete for {self.output_id}")

        return self.client.get_entity(morphology.id, entity_type=CellMorphology)

    def cleanup(self) -> None:
        """Cleanup the skeletonization output"""
        rm_dir(self.path)
        logger.info(f"Cleaned up skeletonization output {self.path}")
