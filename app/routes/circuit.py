from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import UUID4
from rq import Queue

from app.domains.circuit.morphology_pack import MorphologyPackStatus
from app.domains.circuit.simulation import RunBatchRequest
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep, UserAuthDep
from app.services.api.circuit.morphology_pack import (
    get_morphology_pack,
    get_morphology_pack_status,
)
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
    auth: UserAuthDep,
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
    auth: UserAuthDep,
    job_queue: Queue = Depends(queue_factory(JobQueue.LOW)),
):
    return await run_circuit_simulation_batch_service(
        run_batch_request.simulation_ids,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        auth=auth,
    )


@router.post(
    "/{circuit_id}/morphology-pack",
    tags=["circuit", "morphology-pack"],
    description="The state of the circuit's morphology pack. Queues its build if it isn't built",
)
async def request_morphology_pack(
    circuit_id: UUID,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
) -> MorphologyPackStatus:
    return await get_morphology_pack_status(circuit_id, auth=auth, project_context=project_context)


@router.get(
    "/{circuit_id}/morphology-pack",
    tags=["circuit", "morphology-pack"],
    description="The circuit's morphology pack, once it is built",
    response_class=FileResponse,
)
async def download_morphology_pack(
    circuit_id: UUID,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
) -> FileResponse:
    return await get_morphology_pack(circuit_id, auth=auth, project_context=project_context)
