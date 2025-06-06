"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Body, Depends
from app.infrastructure.kc.auth import verify_jwt, Auth
from app.services.api.single_cell.validate_synapse_formula import (
    validate_synapse_generation_formula,
)
from app.domains.morphology import (
    SynapsePlacementResponse,
)


router = APIRouter(prefix="/validation")


@router.post(
    "/synapse-formula",
    response_model=bool,
)
def place_synapses(
    formula: str = Body(embed=True),
    _: Auth = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    return validate_synapse_generation_formula(formula=formula)  # type: ignore
