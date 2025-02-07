from bluenaas.services.morphology import get_single_morphology
from bluenaas.services.morphology_dendrogram import get_single_morphology_dendrogram
from fastapi import APIRouter, Depends, Query, Request

from bluenaas.infrastructure.kc.auth import verify_jwt, Auth

router = APIRouter(prefix="/morphology")


@router.get("")
def retrieve_morphology(
    request: Request,
    model_self: str = Query(""),
    auth: Auth = Depends(verify_jwt),
):
    return get_single_morphology(
        model_id=model_self,
        token=auth.token,
        req_id=request.state.request_id,
    )


@router.get("/dendrogram")
def retrieve_morphology_dendrogram(
    request: Request,
    model_id: str = Query(""),
    auth: Auth = Depends(verify_jwt),
):
    return get_single_morphology_dendrogram(
        model_id=model_id,
        token=auth.token,
        req_id=request.state.request_id,
    )
