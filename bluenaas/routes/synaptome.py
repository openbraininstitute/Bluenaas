"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Depends, Query, Request
from bluenaas.domains.morphology import (
    SynapsePlacementBody,
    SynapsePlacementResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.services.synapses_placement import generate_synapses_placement


router = APIRouter(prefix="/synaptome")


@router.post(
    "/generate-placement",
    response_model=SynapsePlacementResponse,
)
def place_synapses(
    request: Request,
    params: SynapsePlacementBody,
    model_id: str = Query(),
    auth: Auth = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    return generate_synapses_placement(
        model_id=model_id,
        token=auth.token,
        params=params,
        req_id=request.state.request_id,
    )
