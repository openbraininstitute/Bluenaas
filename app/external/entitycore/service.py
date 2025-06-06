from concurrent.futures import ThreadPoolExecutor
from typing import Annotated
from uuid import UUID

import requests
from fastapi import Header
from loguru import logger
from pydantic import BaseModel

from app.config.settings import settings
from app.core.exceptions import SimulationError
from app.core.types import FileObj
from app.external.base import Service
from app.external.entitycore.schemas import (
    EModelReadExpanded,
    EntityRoute,
    MEModelRead,
    ReconstructionMorphologyRead,
)


class ProjectContext(BaseModel):
    virtual_lab_id: UUID
    project_id: UUID


ProjectContextDep = Annotated[ProjectContext, Header()]


def entitycore_url():
    return str(settings.ENTITYCORE_URI).rstrip("/")


def fetch_one[T: BaseModel](
    id: UUID,
    route: EntityRoute,
    token: str,
    response_class: type[T],
    project_context: ProjectContext,
) -> T:
    res = requests.get(
        f"{entitycore_url()}/{route.value}/{id}",
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
        f"{entitycore_url()}/{entity_route.value}/{entity_id}/assets/{id}/download",
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
    hoc_file_id = next(
        (
            asset.id
            for asset in emodel.assets
            if asset.content_type == "application/hoc"
        ),
        None,
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

    formats = ["application/asc", "application/swc", "application/h5"]

    for format in formats:
        for asset in morphology.assets:
            if asset.content_type == format:
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


def fetch_icms(emodel: EModelReadExpanded, token: str, project_context: ProjectContext):
    icms = emodel.ion_channel_models

    mod_files: list[FileObj] = []

    with ThreadPoolExecutor() as executor:
        for icm in icms:
            for asset in icm.assets:
                if asset.content_type == "application/neuron-mod":
                    future = executor.submit(
                        download_asset,
                        asset.id,
                        icm.id,
                        EntityRoute.ion_channel_model,
                        token,
                        project_context=project_context,
                    )

                    mod_files.append(
                        FileObj(
                            name=asset.path,
                            content=future.result(),
                        )
                    )

    return mod_files


class EntityCore(Service):
    def __init__(self, token: str, model_id: str, project_context: ProjectContext):
        self.token = token
        self.model_id = model_id
        self.model_uuid = model_id
        self.model: MEModelRead | None = None
        self.project_context = project_context

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

        hoc_file = fetch_hoc_file(
            emodel,
            self.token,
            project_context=self.project_context,
        )

        morphology = fetch_morphology(
            self.model.morphology.id, self.token, project_context=self.project_context
        )
        icms = fetch_icms(emodel, self.token, project_context=self.project_context)

        logger.debug("\n\n\nCreating model folder")
        self.create_model_folder(hoc_file, morphology, icms)
        logger.debug("E-Model folder created")
