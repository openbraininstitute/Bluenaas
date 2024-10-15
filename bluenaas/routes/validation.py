"""
Validation endpoints
"""

from fastapi import APIRouter, Depends

from bluenaas.domains.validation import (
    PlaceSynapsesBodyRequest,
    PlaceSynapsesFormulaValidationResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.validate_synapse_formula import (
    validate_synapse_generation_formula,
)

router = APIRouter(
    prefix="/validation",
    tags=["Validation"],
)


@router.post(
    "/synapse-formula",
    response_model=PlaceSynapsesFormulaValidationResponse,
    summary="Validate synapse generation formula",
)
def place_synapses(
    request: PlaceSynapsesBodyRequest,
    _: str = Depends(verify_jwt),
):
    """
    This endpoint accepts a synapse generation formula and validates its
    syntax and correctness. A valid formula is essential for accurate
    synapse generation.

    Args:

        formula (str): The synapse generation mathematical formula to be validated.

    Returns:

        SynaptomeFormulaResponse: A response model indicating the result
                                  of the formula validation, including
                                  any error messages or confirmation
                                  of validity.
    """
    return validate_synapse_generation_formula(
        formula=request.formula,
    )
