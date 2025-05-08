from uuid import UUID
import requests
from bluenaas.config.settings import settings
from bluenaas.external.entitycore.schemas import (
    EntityRoute,
    EModelReadExpanded,
    MEModelRead,
    ReconstructionMorphologyRead,
    AssetRead,
)
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor
from bluenaas.external.nexus.nexus import Nexus
from loguru import logger


def fetch_one[T: BaseModel](
    id: UUID,
    route: EntityRoute,
    # virtual_lab_id: UUID,
    # project_id: UUID,
    token: str,
    response_class: type[T],
) -> T:
    res = requests.get(
        f"{settings.ENTITYCORE_URI}{route.value}/{id}",
        headers={
            # "virtual_lab_id": str(virtual_lab_id),
            # "project_id": str(project_id),
            "Authorization": token
        },
    )

    res.raise_for_status()

    return response_class.model_validate(res.json())


def download_asset(
    id: UUID,
    entity_id: UUID,
    entity_route: EntityRoute,
    token: str,
    # virtual_lab_id: UUID,
    # project_id: UUID
):
    res = requests.get(
        f"{settings.ENTITYCORE_URI}{entity_route.value}/{entity_id}/assets/{id}/download"
    )

    res.raise_for_status()

    return res.text


def fetch_hoc_file(emodel: EModelReadExpanded, token: str):
    e_model_assets = emodel.assets or []

    hoc_file_id = next(
        (asset.id for asset in e_model_assets if asset.path == "model.hoc"), None
    )

    if not hoc_file_id:
        raise ValueError(f"hoc_file not found for emodel {emodel.id}")

    return download_asset(hoc_file_id, emodel.id, EntityRoute.emodel, token=token)


def fetch_morphology(id: UUID, token: str):
    morphology = fetch_one(
        id, EntityRoute.reconstruction_morphology, token, ReconstructionMorphologyRead
    )

    assets_by_type: dict[str, AssetRead] = {}

    asset: AssetRead | None = None

    for asset in morphology.assets or []:
        if asset.path.endswith("swc"):
            assets_by_type["swc"] = asset

        if asset.path.endswith("asc"):
            assets_by_type["asc"] = asset

    asset = assets_by_type.get("asc") or assets_by_type.get("swc")

    if not asset:
        raise ValueError(f"No morphology files found for morphology {id}")

    return download_asset(
        asset.id, id, EntityRoute.reconstruction_morphology, token=token
    )


def fetch_mechanisms(emodel: EModelReadExpanded, token: str):
    icms = emodel.ion_channel_models

    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(
                download_asset, asset.id, icm.id, EntityRoute.ion_channel_model, token
            )
            for icm in icms
            for asset in icm.assets or []
            if asset.path.endswith("mod")
        ]

    return [f.result() for f in futures]


class EntityCore(Nexus):
    def __init__(self, token: str, model_id: UUID):
        self.token = token
        self.model_id = model_id
        self.model: MEModelRead | None = None

    def get_currents(self):
        if not self.model:
            self.model = fetch_one(
                self.model_id,
                EntityRoute.memodel,
                token=self.token,
                response_class=MEModelRead,
            )

        return [self.model.holding_current, self.model.threshold_current]

    def get_model_uuid(self):
        return str(self.model_id)

    def download_model(self):
        if not self.model:
            self.model = fetch_one(
                self.model_id,
                EntityRoute.memodel,
                token=self.token,
                response_class=MEModelRead,
            )

        emodel = fetch_one(
            self.model.emodel.id,
            EntityRoute.emodel,
            token=self.token,
            response_class=EModelReadExpanded,
        )

        e_model_assets = emodel.assets or []

        hoc_file_id = next(
            (asset.id for asset in e_model_assets if asset.path == "model.hoc"), None
        )

        if not hoc_file_id:
            raise ValueError(f"hoc_file not found for emodel {emodel.id}")

        hoc_file = fetch_hoc_file(emodel, token=self.token)
        morphology = fetch_morphology(self.model.morphology.id, self.token)
        mechanisms = fetch_mechanisms(emodel, self.token)

        self.create_model_folder(hoc_file, morphology, mechanisms)
        logger.debug("E-Model folder created")
