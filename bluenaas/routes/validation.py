"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Body, Depends, Request

from bluenaas.infrastructure.kc.auth import verify_jwt
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
    token: str = Depends(verify_jwt),
):
    return validate_synapse_generation_formula(formula=formula)
