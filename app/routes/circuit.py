from fastapi import APIRouter, Depends, Request

from rq import Queue

from app.infrastructure.kc.auth import verify_jwt, Auth
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.circuit.simulation import (
    SimulationRequest,
    run_circuit_simulation as run_circuit_simulation_service,
)

router = APIRouter(prefix="/circuit")


@router.post("/simulation/run", tags=["simulation"])
async def run_circuit_simulation(
    request: Request,
    simulation_request: SimulationRequest,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
    # realtime: bool = True,
):
    return await run_circuit_simulation_service(
        request=request,
        job_queue=job_queue,
        simulation_request=simulation_request,
        access_token=auth.access_token,
    )
