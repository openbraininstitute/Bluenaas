from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, Query, Depends

from app.domains.simulation import PaginatedResponse
from app.infrastructure.kc.auth import verify_jwt, Auth
from app.domains.neuron_model import (
    SynaptomeModelResponse,
    MEModelResponse,
)
from app.services.neuron_model.get_all_neuron_models_for_project import (
    get_all_neuron_models_for_project,
)
from app.services.neuron_model.get_neuron_model_for_project import (
    get_neuron_model_for_project,
)

router = APIRouter(
    prefix="/neuron-model",
    tags=["Neuron Models"],
)


@router.get(
    "/{virtual_lab_id}/{project_id}/me-models",
    summary="Retrieve all me models for a specific project",
)
def retrieve_neuron_models(
    virtual_lab_id: str,
    project_id: str,
    offset: int = 0,
    page_size: int = 20,
    model_type: Optional[Literal["me-model", "synaptome"]] = None,
    created_at_start: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    created_at_end: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    auth: Auth = Depends(verify_jwt),
) -> PaginatedResponse[MEModelResponse | SynaptomeModelResponse]:
    return get_all_neuron_models_for_project(
        token=auth.access_token,
        org_id=virtual_lab_id,
        project_id=project_id,
        offset=offset,
        size=page_size,
        model_type=model_type,
        created_at_start=created_at_start,
        created_at_end=created_at_end,
    )


@router.get(
    "/{virtual_lab_id}/{project_id}/{model_id:path}",
    summary="Retrieve specific model in a project",
)
def retrieve_neuron_model(
    virtual_lab_id: str,
    project_id: str,
    model_id: str,
    auth: Auth = Depends(verify_jwt),
) -> MEModelResponse | SynaptomeModelResponse:
    return get_neuron_model_for_project(
        token=auth.access_token,
        org_id=virtual_lab_id,
        project_id=project_id,
        model_self=model_id,
    )
