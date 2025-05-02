from uuid import UUID
import requests
from bluenaas.config.settings import settings
from bluenaas.external.entitycore.schemas import EntityRoute
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
