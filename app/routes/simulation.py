"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from fastapi import APIRouter, Depends, Request, Query
from typing import Optional
from datetime import datetime

from rq import Queue

from app.domains.simulation import (
    SimulationDetailsResponse,
    SingleNeuronSimulationConfig,
    SimulationType,
    PaginatedResponse,
)
from app.domains.nexus import DeprecateNexusResponse
from app.infrastructure.kc.auth import verify_jwt, Auth
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.shared.single_cell.fetch_simulation_status_and_results import (
    fetch_simulation_status_and_results,
)
from app.services.shared.single_cell.deprecate_simulation import deprecate_simulation
from app.services.shared.single_cell.fetch_all_simulations_of_project import (
    fetch_all_simulations_of_project,
)
from app.services.api.single_cell.simulation import (
    run_simulation as run_simulation_service,
)

router = APIRouter(prefix="/simulation")


@router.post("/single-neuron/{virtual_lab_id}/{project_id}/run", tags=["simulation"])
async def run_simulation(
    request: Request,
    virtual_lab_id: str,
    project_id: str,
    model_id: str,
    config: SingleNeuronSimulationConfig,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
    realtime: bool = True,
):
    """
    Run a neuron simulation and optionally get results in realtime.
    If `realtime` query parameter is False only the simulation id is returned which can be used to retrieve status and result
    of simulation.

    Returns:
    --------
    If realtime is True - A StreamingResponse is returned which contains chunks of simulation data of type `SimulationItemResponse`

    If realtime is False - `BackgroundSimulationStatusResponse` is returned with simulation `id`. This `id` can be url-encoded and
    used to later query the status (and get result if any) of simulation.
    """
    return await run_simulation_service(
        virtual_lab_id=virtual_lab_id,
        project_id=project_id,
        request=request,
        model_id=model_id,
        config=config,
        job_queue=job_queue,
        auth=auth,
        realtime=realtime,
    )


@router.get(
    "/single-neuron/{virtual_lab_id}/{project_id}",
    description="Get all simulations for a project",
    summary=(
        """
        Returns all simulations in the provided project. 
        Please note, the data for simulations does not contain simulation results (x, y points) 
        or simulation config to not bloat the response.
        Only nexus simulations that conform with the latest schema are returned.
        """
    ),
    tags=["simulation"],
)
async def get_all_simulations_for_project(
    virtual_lab_id: str,
    project_id: str,
    simulation_type: Optional[SimulationType] = None,
    offset: int = 0,
    page_size: int = 20,
    created_at_start: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    created_at_end: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    auth: Auth = Depends(verify_jwt),
) -> PaginatedResponse[SimulationDetailsResponse]:
    return fetch_all_simulations_of_project(
        token=auth.access_token,
        org_id=virtual_lab_id,
        project_id=project_id,
        sim_type=simulation_type,
        offset=offset,
        size=page_size,
        created_at_start=created_at_start,
        created_at_end=created_at_end,
    )


@router.get(
    "/single-neuron/{virtual_lab_id}/{project_id}/{simulation_id:path}",
    summary=(
        """
        Get results & status for a previously started simulation. 
        If simulation is not complete the results are null.
        `simulation_id` should be url encoded.
        """
    ),
    tags=["simulation"],
)
async def get_simulation(
    virtual_lab_id: str,
    project_id: str,
    simulation_id: str,
    auth: Auth = Depends(verify_jwt),
) -> SimulationDetailsResponse:
    return fetch_simulation_status_and_results(
        token=auth.access_token,
        org_id=virtual_lab_id,
        project_id=project_id,
        simulation_uri=simulation_id,
    )


@router.delete(
    "/single-neuron/{virtual_lab_id}/{project_id}/{simulation_id:path}",
    summary="Delete simulation resource",
    tags=["simulation"],
)
async def delete_simulation(
    virtual_lab_id: str,
    project_id: str,
    simulation_id: str,
    auth: Auth = Depends(verify_jwt),
) -> DeprecateNexusResponse:
    return deprecate_simulation(
        token=auth.access_token,
        org_id=virtual_lab_id,
        project_id=project_id,
        simulation_uri=simulation_id,
    )
