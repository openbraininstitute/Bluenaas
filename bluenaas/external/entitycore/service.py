from uuid import UUID
import requests
from bluenaas.config.settings import settings
from bluenaas.external.entitycore.schemas import EntityRoute, EModelReadExpanded
from pydantic import BaseModel


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


def fetch_hoc_file(emodel_id: UUID, token: str):
    emodel = fetch_one(
        emodel_id,
        EntityRoute.emodel,
        token=token,
        response_class=EModelReadExpanded,
    )

    e_model_assets = emodel.assets or []

    hoc_file_id = next(
        (asset.id for asset in e_model_assets if asset.path == "model.hoc"), None
    )

    if not hoc_file_id:
        raise ValueError(f"hoc_file not found for emodel {emodel.id}")

    return download_asset(hoc_file_id, emodel.id, EntityRoute.emodel, token=token)


def fetch_morphology(id: UUID, token: str):
    morphology = fetch_one(
        
    )
