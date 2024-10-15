from fastapi import APIRouter, Depends, Query, Request

from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.morphology import get_single_morphology
from bluenaas.services.morphology_dendrogram import get_single_morphology_dendrogram

router = APIRouter(
    prefix="/morphology",
    tags=["Morphology"],
)


@router.get(
    "",
    summary="Retrieve morphology data",
)
def retrieve_morphology(
    request: Request,
    model_self: str = Query(""),
    token: str = Depends(verify_jwt),
):
    """
    Retrieves morphology data for a specified model.

    Args:

        model_self (str): The unique identifier of the model for which
                          morphology data is requested.

    Returns:

        MorphologyResponse: A response model containing the morphology data
                            for the specified model.

    Raises:

        HTTPException: If the request is invalid or if there is an error
                       during the retrieval of morphology data, an appropriate
                       HTTP exception will be raised with the corresponding
                       error message and status code.

    """
    return get_single_morphology(
        model_self=model_self,
        token=token,
        req_id=request.state.request_id,
    )


@router.get(
    "/dendrogram",
    summary="Retrieve dendrogram morphology data",
)
def retrieve_morphology_dendrogram(
    request: Request,
    model_self: str = Query(""),
    token: str = Depends(verify_jwt),
):
    """
    Retrieves dendrogram morphology data for a specified model.

    Args:

        model_self (str): The unique identifier of the model for which
                          dendrogram morphology data is requested.

    Returns:

        DendrogramResponse: A response model containing the dendrogram morphology data
                            for the specified model.

    Raises:

        HTTPException: If the request is invalid or if there is an error
                       during the retrieval of dendrogram morphology data,
                       an appropriate HTTP exception will be raised with
                       the corresponding error message and status code.

    """
    return get_single_morphology_dendrogram(
        model_self=model_self,
        token=token,
        req_id=request.state.request_id,
    )
