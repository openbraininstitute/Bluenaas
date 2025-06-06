"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from fastapi import APIRouter, Depends, Request

from rq import Queue

from app.infrastructure.kc.auth import verify_jwt, Auth
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.circuit.simulation import (
    run_circuit_simulation as run_circuit_simulation_service,
)

router = APIRouter(prefix="/circuit")


# @router.get("/circuit/{virtual_lab_id}/{project_id}/run", tags=["simulation"])
@router.get("/simulation/run", tags=["simulation"])
def run_circuit_simulation(
    request: Request,
    # virtual_lab_id: str,
    # project_id: str,
    # auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
    # realtime: bool = True,
):
    return run_circuit_simulation_service(request, job_queue)
