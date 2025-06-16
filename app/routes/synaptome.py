"""
Synapse Placement Generation:
Exposes an endpoint (`/generate-placement`) to generate synapse placements based on user-provided parameters
"""

from fastapi import APIRouter, Depends, Query, Request
from rq import Queue

from app.domains.morphology import (
    SynapsePlacementBody,
    SynapsePlacementResponse,
)
from app.external.entitycore.service import ProjectContextDep
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_cell.synapse import generate_synapses

router = APIRouter(prefix="/synaptome")


@router.post(
    "/generate-placement",
    response_model=SynapsePlacementResponse,
)
async def place_synapses(
    request: Request,
    params: SynapsePlacementBody,
    project_context: ProjectContextDep,
    model_id: str = Query(),
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
) -> SynapsePlacementResponse | None:
    return await generate_synapses(
        request=request,
        queue=job_queue,
        model_id=model_id,
        token=auth.token,
        params=params,
        entitycore=False,
        virtual_lab_id=str(project_context.virtual_lab_id),
        project_id=str(project_context.project_id),
    )
