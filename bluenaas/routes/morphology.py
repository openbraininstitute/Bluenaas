from bluenaas.services.morphology import get_single_morphology
from fastapi import APIRouter, Depends, Query, Request

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
