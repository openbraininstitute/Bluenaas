from uuid import UUID
from typing import Annotated
from fastapi import Header
import requests
from bluenaas.config.settings import settings
from bluenaas.external.entitycore.schemas import (
    EntityRoute,
    EModelReadExpanded,
    MEModelRead,
    ReconstructionMorphologyRead,
)
from bluenaas.core.exceptions import SimulationError
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor
from bluenaas.core.types import FileObj
from bluenaas.external.nexus.nexus import Nexus
from loguru import logger


class ProjectContext(BaseModel):
    virtual_lab_id: UUID
    project_id: UUID


ProjectContextDep = Annotated[ProjectContext, Header()]


def fetch_one[T: BaseModel](
    id: UUID,
    route: EntityRoute,
    token: str,
    response_class: type[T],
    project_context: ProjectContext,
) -> T:
    res = requests.get(
        f"{settings.ENTITYCORE_URI}{route.value}/{id}",
        headers={
            "virtual-lab-id": str(project_context.virtual_lab_id),
            "project-id": str(project_context.project_id),
            "Authorization": token,
        },
    )

    res.raise_for_status()

    return response_class.model_validate(res.json())


def download_asset(
    id: UUID,
    entity_id: UUID,
    entity_route: EntityRoute,
    token: str,
    project_context: ProjectContext,
):
    res = requests.get(
        f"{settings.ENTITYCORE_URI}{entity_route.value}/{entity_id}/assets/{id}/download",
        headers={
            "virtual-lab-id": str(project_context.virtual_lab_id),
            "project-id": str(project_context.project_id),
            "Authorization": token,
        },
    )

    res.raise_for_status()

    return res.text


def fetch_hoc_file(
    emodel: EModelReadExpanded, token: str, project_context: ProjectContext
):
    e_model_assets = emodel.assets or []

    hoc_file_id = next(
        (asset.id for asset in e_model_assets if asset.path == "model.hoc"), None
    )

    if not hoc_file_id:
        raise ValueError(f"hoc_file not found for emodel {emodel.id}")

    return download_asset(
        hoc_file_id,
        emodel.id,
        EntityRoute.emodel,
        token=token,
        project_context=project_context,
    )


def fetch_morphology(id: UUID, token: str, project_context: ProjectContext):
    morphology = fetch_one(
        id,
        EntityRoute.reconstruction_morphology,
        token,
        ReconstructionMorphologyRead,
        project_context=project_context,
    )

    if not morphology.assets:
        raise SimulationError(f"No morphology files found for morphology {id}")

    formats = ["asc", "swc", "h5"]

    for format in formats:
        for asset in morphology.assets:
            asset_format = asset.path.split(".")[-1].lower()
            if asset_format == format:
                return FileObj(
                    name=asset.path,
                    content=download_asset(
                        asset.id,
                        id,
                        EntityRoute.reconstruction_morphology,
                        token,
                        project_context=project_context,
                    ),
                )

    raise SimulationError(
        f"Morphology {id} does not have a valid file format. Valid formats are {', '.join(formats)}"
    )


def fetch_mechanisms(
    emodel: EModelReadExpanded, token: str, project_context: ProjectContext
):
    icms = emodel.ion_channel_models

    mechanisms: list[FileObj] = []

    with ThreadPoolExecutor() as executor:
        for icm in icms:
            for asset in icm.assets or []:
                if asset.path.endswith("mod"):
                    future = executor.submit(
                        download_asset,
                        asset.id,
                        icm.id,
                        EntityRoute.ion_channel_model,
                        token,
                        project_context=project_context,
                    )

                    mechanisms.append(
                        FileObj(
                            name=asset.path,
                            content=future.result(),
                        )
                    )

    return mechanisms


class EntityCore(Nexus):
    def __init__(
        self, token: str, model_id: str, project_Context: ProjectContext
    ):
        self.token = token
        self.model_id = model_id
        self.model: MEModelRead | None = None
        self.project_context = project_Context

    @property
    def model_uuid(self):
        return self.model_id

    def get_currents(self) -> list[float]:
        if not self.model:
            self.model = fetch_one(
                UUID(self.model_id),
                EntityRoute.memodel,
                token=self.token,
                response_class=MEModelRead,
                project_context=self.project_context,
            )

        return [self.model.holding_current or 0, self.model.threshold_current or 0.1]

    def get_model_uuid(self):
        return str(self.model_id)

    def download_model(self):
        if not self.model:
            self.model = fetch_one(
                UUID(self.model_id),
                EntityRoute.memodel,
                token=self.token,
                response_class=MEModelRead,
                project_context=self.project_context,
            )

        emodel = fetch_one(
            self.model.emodel.id,
            EntityRoute.emodel,
            token=self.token,
            response_class=EModelReadExpanded,
            project_context=self.project_context,
        )

        e_model_assets = emodel.assets or []

        hoc_file_id = next(
            (asset.id for asset in e_model_assets if asset.path == "model.hoc"), None
        )

        if not hoc_file_id:
            raise ValueError(f"hoc_file not found for emodel {emodel.id}")

        hoc_file = fetch_hoc_file(
            emodel,
            self.token,
            project_context=self.project_context,
        )
        morphology = fetch_morphology(
            self.model.morphology.id, self.token, project_context=self.project_context
        )
        mechanisms = fetch_mechanisms(
            emodel, self.token, project_context=self.project_context
        )

        logger.debug("\n\n\nCreating model folder")
        self.create_model_folder(hoc_file, morphology, mechanisms)
        logger.debug("E-Model folder created")
