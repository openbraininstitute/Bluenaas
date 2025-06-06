"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from rq import Queue

from app.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from app.external.entitycore.service import ProjectContextDep
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_cell.simulation import (
    run_simulation as run_simulation_service,
)

router = APIRouter(prefix="/simulation")


@router.post("/single-neuron/{virtual_lab_id}/{project_id}/run", tags=["simulation"])
def run_simulation(
    request: Request,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return run_simulation_service(
        request=request,
        job_queue=job_queue,
        virtual_lab_id=str(project_context.virtual_lab_id),
        project_id=str(project_context.project_id),
        model_id=str(model_id),
        config=config,
        auth=auth,
        realtime=True,
        entitycore=True,
    )
