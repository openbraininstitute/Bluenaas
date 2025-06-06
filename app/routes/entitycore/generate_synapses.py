"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Body, Depends, Query, Request

from app.domains.morphology import (
    SynapsePlacementBody,
    SynapsePlacementResponse,
)
from app.external.entitycore.service import ProjectContextDep
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.services.synapses_placement import generate_synapses_placement

router = APIRouter(prefix="/synaptome")


@router.post(
    "/generate-placement",
    response_model=SynapsePlacementResponse,
)
def place_synapses(
    request: Request,
    project_context: ProjectContextDep,
    params: SynapsePlacementBody = Body(...),
    model_id: str = Query(),
    auth: Auth = Depends(verify_jwt),
) -> SynapsePlacementResponse | None:
    return generate_synapses_placement(
        model_id=model_id,
        token=auth.token,
        params=params,
        is_entitycore=True,
        req_id=request.state.request_id,
        virtual_lab_id=str(project_context.virtual_lab_id),
        project_id=str(project_context.project_id),
    )
