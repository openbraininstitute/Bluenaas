"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Body, Depends, Request
from bluenaas.domains.morphology import (
    SynapsePlacementResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.services.validate_synapse_formula import (
    validate_synapse_generation_formula,
)


router = APIRouter(prefix="/validation")


@router.post(
    "/synapse-formula",
    response_model=bool,
)
def place_synapses(
    request: Request,
    formula: str = Body(embed=True),
    auth: Auth = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    return validate_synapse_generation_formula(formula=formula)
