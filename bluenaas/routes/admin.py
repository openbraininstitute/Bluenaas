from fastapi import APIRouter, Depends, Response
from fastapi.background import BackgroundTasks

from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.services.model_cache import clear_cache


router = APIRouter(prefix="/admin")


@router.delete("/model-cache")
def delete_cache(
    background_tasks: BackgroundTasks,
    auth: Auth = Depends(verify_jwt),
):
    # TODO: figure out the authorization

    background_tasks.add_task(clear_cache)

    return Response(status_code=202)
