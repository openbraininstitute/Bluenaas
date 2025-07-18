from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import requests
from entitysdk.common import ProjectContext
from entitysdk.types import AssetLabel, ContentType
from loguru import logger
from pydantic import BaseModel

from app.config.settings import settings
from app.core.exceptions import SimulationError
from app.core.types import FileObj
from app.external.base import Service
from app.external.entitycore.schemas import (
    EModelReadExpanded,
    EntityRoute,
    IonChannelModelWAssets,
    MEModelRead,
    ReconstructionMorphologyRead,
)


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
            "Authorization": f"Bearer {token}",
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
            "Authorization": f"Bearer {token}",
        },
    )
    res.raise_for_status()

    return res.content


def fetch_hoc_file(emodel: EModelReadExpanded, token: str, project_context: ProjectContext):
    hoc_file_id = next(
        (asset.id for asset in emodel.assets if asset.label == AssetLabel.neuron_hoc),
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

    formats = [
        ContentType.application_asc,
        ContentType.application_swc,
        ContentType.application_x_hdf5,
    ]

    for format in formats:
        for asset in morphology.assets:
            if asset.content_type.value == format.value:
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
        f"Morphology {id} does not have a valid file format. Valid formats are {formats}"
    )


def iter_matching_assets(icms: list[IonChannelModelWAssets]):
    for icm in icms:
        yield from (
            (icm, asset) for asset in icm.assets if asset.label == AssetLabel.neuron_mechanisms
        )


def fetch_icms(emodel: EModelReadExpanded, token: str, project_context: ProjectContext):
    icms = emodel.ion_channel_models

    mod_files: list[FileObj] = []

    with ThreadPoolExecutor() as executor:
        futures = [
            (
                asset.path,
                executor.submit(
                    download_asset,
                    asset.id,
                    icm.id,
                    EntityRoute.ion_channel_model,
                    token,
                    project_context=project_context,
                ),
            )
            for icm, asset in iter_matching_assets(icms)
        ]

        for name, future in futures:
            mod_files.append(FileObj(name=name, content=future.result()))

    return mod_files


class EntityCore(Service):
    def __init__(self, model_id: UUID, access_token: str, project_context: ProjectContext):
        self.access_token = access_token
        self.model_id = model_id
        self.model: MEModelRead | None = None
        self.project_context = project_context

    def get_currents(self) -> list[float]:
        if not self.model:
            self.model = fetch_one(
                self.model_id,
                EntityRoute.memodel,
                token=self.access_token,
                response_class=MEModelRead,
                project_context=self.project_context,
            )

        return [
            self.model.calibration_result and self.model.calibration_result.holding_current or 0,
            self.model.calibration_result
            and self.model.calibration_result.threshold_current
            or 0.1,
        ]

    def download_model(self):
        if not self.model:
            self.model = fetch_one(
                self.model_id,
                EntityRoute.memodel,
                token=self.access_token,
                response_class=MEModelRead,
                project_context=self.project_context,
            )

        emodel = fetch_one(
            self.model.emodel.id,
            EntityRoute.emodel,
            token=self.access_token,
            response_class=EModelReadExpanded,
            project_context=self.project_context,
        )

        hoc_file = fetch_hoc_file(
            emodel,
            self.access_token,
            project_context=self.project_context,
        )

        morphology = fetch_morphology(
            self.model.morphology.id,
            self.access_token,
            project_context=self.project_context,
        )
        icms = fetch_icms(emodel, self.access_token, project_context=self.project_context)

        logger.debug("Creating model folder")
        self.create_model_folder(hoc_file, morphology, icms)
        logger.debug("E-Model folder created")
