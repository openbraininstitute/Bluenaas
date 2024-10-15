"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Depends, Query, Request
from bluenaas.domains.morphology import (
    SynapsePlacementBody,
    SynapsePlacementResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.synapses_placement import generate_synapses_placement


router = APIRouter(
    prefix="/synaptome",
    tags=["Synaptome"],
)


@router.post(
    "/generate-placement",
    response_model=SynapsePlacementResponse,
    summary="Retrieve synapses positions coordinates for 3D plan",
)
def place_synapses(
    request: Request,
    params: SynapsePlacementBody,
    model_id: str = Query(),
    token: str = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    """
    Generates synapse position coordinates for a 3D plan based on the provided parameters.

    This endpoint accepts a set of parameters to calculate the positions of synapses
    in a 3D model.

    Args:

        params (SynapsePlacementBody): A body model containing the necessary
                                        parameters for synapse placement.

        model_id (str): The unique identifier of the model for which synapses
                        are to be placed.

    Returns:

        SynapsePlacementResponse: A response model containing the coordinates
                                  of the synapses positions for the 3D plan.

    Raises:

        HTTPException: If the request is invalid or if there is an error
                       during the synapse placement generation, an appropriate
                       HTTP exception will be raised with the corresponding
                       error message and status code.

    """
    return generate_synapses_placement(
        model_id=model_id,
        token=token,
        params=params,
        req_id=request.state.request_id,
    )
