from pathlib import Path
from typing import cast
from uuid import UUID

from entitysdk.client import Client
from entitysdk.models import BrainRegion, CellMorphology, Contribution, License, Role, Subject
from entitysdk.models.asset import AssetLabel, ContentType
from entitysdk.models.cell_morphology_protocol import (
    CellMorphologyProtocol,
    PlaceholderCellMorphologyProtocol,
)
from loguru import logger
from morphio.mut import Morphology
from pydantic import BaseModel

from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir

CELL_MORPHOLOGY_PROTOCOL_DESCRIPTION = (
    "Skeletonization of a cell surface mesh with optional extraction of spines"
)
CELL_MORPHOLOGY_PROTOCOL_NAME = "Ultraliser skeletonization"
LICENSE_LABEL = "CC BY-NC 4.0"
ROLE_NAME = "data modeling role"
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
        # Clean up *-morphology.h5 and *-spines.h5 files from the output
        for pattern in ("*-morphology.h5", "*-spines.h5"):
            for file in self.path.rglob(pattern):
                file.unlink()

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

        license = cast(
            License | None,
            next(
                self.client.search_entity(
                    entity_type=License,
                    query={"label": LICENSE_LABEL},
                ),
                None,
            ),
        )
        if not license:
            raise ValueError(f"License {LICENSE_LABEL} not found")

        role = cast(
            Role | None,
            next(
                self.client.search_entity(
                    entity_type=Role,
                    query={"name": ROLE_NAME},
                ),
                None,
            ),
        )
        if not role:
            raise ValueError(f"Role {ROLE_NAME} not found")

        protocol = cast(
            PlaceholderCellMorphologyProtocol | None,
            next(
                self.client.search_entity(
                    entity_type=CellMorphologyProtocol,
                    query={"name": CELL_MORPHOLOGY_PROTOCOL_NAME},
                ),
                None,
            ),
        )
        if not protocol:
            logger.debug(f"Creating cell morphology protocol: {CELL_MORPHOLOGY_PROTOCOL_NAME}")
            protocol = self.client.register_entity(
                PlaceholderCellMorphologyProtocol(
                    name=CELL_MORPHOLOGY_PROTOCOL_NAME,
                    description=CELL_MORPHOLOGY_PROTOCOL_DESCRIPTION,
                )
            )

        morphology = cast(
            CellMorphology,
            self.client.register_entity(
                CellMorphology(
                    name=self.metadata.name,
                    description=self.metadata.description,
                    cell_morphology_protocol=protocol,
                    brain_region=self.metadata.brain_region,
                    subject=self.metadata.subject,
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
