from bluenaas.services.morphology import get_single_morphology
from bluenaas.services.synapses import generate_synapses_placement
from fastapi import APIRouter, Depends, Query, Request
from bluenaas.domains.morphology import (
    SynapsePlacementBody,
    SynapsePlacementResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt

router = APIRouter(prefix="/morphology")


@router.get("")
def retrieve_morphology(
    request: Request,
    model_id: str = Query(""),
    token: str = Depends(verify_jwt),
):
    return get_single_morphology(
        model_id=model_id,
        token=token,
        req_id=request.state.request_id,
    )


@router.post(
    "/synapses",
    response_model=SynapsePlacementResponse,
)
def place_synapses(
    request: Request,
    params: SynapsePlacementBody,
    model_id: str = Query(),
    token: str = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    return generate_synapses_placement(
        model_id=model_id, token=token, params=params, req_id=request.state.request_id
    )
