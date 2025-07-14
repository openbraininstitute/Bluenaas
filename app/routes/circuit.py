from pydantic import UUID4
from fastapi import APIRouter, Depends, Request

from rq import Queue

from app.routes.dependencies import ProjectContextDep
from app.infrastructure.kc.auth import verify_jwt, Auth
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.circuit.simulation import (
    run_circuit_simulation as run_circuit_simulation_service,
)

router = APIRouter(prefix="/circuit")


@router.post("/simulation/run", tags=["circuit", "simulation"])
async def run_circuit_simulation(
    request: Request,
    simulation_id: UUID4,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.LOW)),
):
    return await run_circuit_simulation_service(
        simulation_id,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        access_token=auth.access_token,
    )
