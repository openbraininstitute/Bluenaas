from fastapi import APIRouter, Depends, Request
from pydantic import UUID4
from rq import Queue

from app.domains.circuit.simulation import RunBatchRequest
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep
from app.services.api.circuit.simulation import (
    run_circuit_simulation as run_circuit_simulation_service,
)
from app.services.api.circuit.simulation import (
    run_circuit_simulation_batch as run_circuit_simulation_batch_service,
)

router = APIRouter(prefix="/circuit")


# TODO Remove endpoint after all dependent services are migrated to run batch.
@router.post(
    "/simulation/run",
    tags=["circuit", "simulation"],
    description="Run a circuit simulation",
    deprecated=True,
)
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
        auth=auth,
    )


@router.post(
    "/simulation/run-batch",
    tags=["circuit", "simulation"],
    description="Run a batch of circuit simulations",
)
async def run_circuit_simulation_batch(
    request: Request,
    run_batch_request: RunBatchRequest,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.LOW)),
):
    return await run_circuit_simulation_batch_service(
        run_batch_request.simulation_ids,
        run_batch_request.circuit_origin,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        auth=auth,
    )
