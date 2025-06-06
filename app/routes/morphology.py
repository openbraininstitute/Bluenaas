from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_cell.morphology import get_morphology_stream
from app.services.morphology_dendrogram import get_single_morphology_dendrogram
from fastapi import APIRouter, Depends, Query, Request
from rq import Queue

from app.infrastructure.kc.auth import verify_jwt, Auth

router = APIRouter(prefix="/morphology")


@router.get("")
def retrieve_morphology(
    request: Request,
    model_self: str = Query(""),
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return get_morphology_stream(
        request=request,
        queue=job_queue,
        model_id=model_self,
        token=auth.token,
    )


# TODO: is this in use?
# @router.get("/dendrogram")
# def retrieve_morphology_dendrogram(
#     request: Request,
#     model_id: str = Query(""),
#     auth: Auth = Depends(verify_jwt),
# ):
#     return get_single_morphology_dendrogram(
#         model_id=model_id,
#         token=auth.token,
#         req_id=request.state.request_id,
#     )
