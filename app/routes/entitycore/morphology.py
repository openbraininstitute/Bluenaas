from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from rq import Queue

from app.infrastructure.kc.auth import verify_jwt, Auth
from app.external.entitycore.service import ProjectContextDep
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_cell.morphology import get_morphology_stream

router = APIRouter(prefix="/morphology")


@router.get("")
def retrieve_morphology(
    request: Request,
    auth: Annotated[Auth, Depends(verify_jwt)],
    model_id: UUID,
    project_context: ProjectContextDep,
    job_queue: Annotated[Queue, Depends(queue_factory(JobQueue.HIGH))],
):
    return get_morphology_stream(
        request=request,
        queue=job_queue,
        model_id=str(model_id),
        token=auth.token,
        entitycore=True,
        project_context=project_context,
    )
