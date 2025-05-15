from uuid import UUID
from typing import Annotated
from bluenaas.services.morphology import get_single_morphology
from fastapi import APIRouter, Depends, Request

from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.external.entitycore.service import ProjectContextDep

router = APIRouter(prefix="/morphology")


@router.get("")
def retrieve_morphology(
    request: Request,
    auth: Annotated[Auth, Depends(verify_jwt)],
    model_id: UUID,
    project_context: ProjectContextDep,
):
    return get_single_morphology(
        model_id=str(model_id),
        token=auth.token,
        req_id=request.state.request_id,
        entity_core=True,
        project_context=project_context,
    )
