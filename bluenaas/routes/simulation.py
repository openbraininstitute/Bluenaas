"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Path, Query, BackgroundTasks
from typing import Optional


from bluenaas.domains.nexus import DeprecateNexusResponse
from bluenaas.domains.simulation import (
    SimulationDetailsResponse,
    SimulationType,
    PaginatedSimulationsResponse,
    SingleNeuronSimulationConfig,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.simulation.run_distributed_simulation import (
    run_distributed_simulation,
)
from bluenaas.services.simulation.shutdown_distributed_simulation import (
    do_shutdown_simulation,
)

from bluenaas.services.simulation.fetch_simulation_status_and_results import (
    fetch_simulation_status_and_results,
)
from bluenaas.services.simulation.deprecate_simulation import deprecate_simulation
from bluenaas.services.simulation.fetch_all_simulations_for_project import (
    fetch_all_simulations_of_project,
)

router = APIRouter(
    prefix="/simulation",
    tags=["Simulation"],
)


@router.post(
    "/single-neuron/{org_id}/{project_id}/run",
    summary="Run neuron simulation distributed per worker",
)
def distributed_simulation(
    model_id: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_jwt),
    realtime: bool = True,
    autosave: bool = True,
):
    """
    Run a distributed neuron simulation across multiple instances, either in autosave or real-time mode.

    Parameters:
    -----------
    `org_id : str`
        The organization ID associated with the simulation.
    `project_id : str`
        The project ID associated with the simulation.
    `model_id : str`
        The URI or identifier for the neuron model being simulated.
    `realtime`: bool
        If realtime is true, simulation results are streamed in chunks. Response type is StreamingResponseWithCleanup.
        If realtime is false, simulation is started in the background and a HTTP JSON Response (of type BackgroundSimulationStatusResponse) or error is returned.
    `autosave`: bool
        If autosave is true, the results of simulations are automatically saved in the database. The response contains the resourceId that can be used to fetch these results.
        Please note, realtime=False and autosave=False is an invalid configuration.

    Returns:
    --------
    StreamingResponseWithCleanup or BackgroundSimulationStatusResponse
        If `realtime` is True, the response is a `StreamingResponseWithCleanup` that streams simulation state to the client.
        If `autosave` is True, the response is a BackgroundSimulationStatusResponse with simulation job details and resources.

    Raises:
    -------
    BlueNaasError
        Raised if there is an internal error during the simulation process.
    Exception
        Raised if there is an issue while streaming simulation data.

    Notes:
    ------
    - The function handles current-varying and frequency-varying simulations.
    - Tasks are distributed as individual simulation instances.
    - The simulation results are either streamed in real time or saved based on the `realtime` and `autosave` flags.
    - If `realtime` is enabled, streaming response is generated to update clients continuously about the state of the simulation.
        and if autosave is enabled too then result will be saved at the end of the simulation at the celery task definition
    - If `autosave` is enabled, the simulation state and results are stored and accessible later through Nexus queries.

    Workflow:
    ---------
    1. Prepare simulation resources if `autosave` is enabled.
    2. Pre-process the simulation, calculating synapses and building the model.
    3. Depending on the simulation type (current or frequency varying), generate tasks for simulation instances.
    4. Group and run tasks asynchronously using Celery's `group`.
    5. If `realtime`, stream the simulation results to the client.
    6. If `autosave`, return a job ID and resources for querying simulation status and results later.

    """
    return run_distributed_simulation(
        org_id=org_id,
        token=token,
        project_id=project_id,
        model_self=model_id,
        config=config,
        autosave=autosave,
        realtime=realtime,
        background_tasks=background_tasks,
    )


@router.post(
    "/single-neuron/{org_id}/{project_id}/{task_id}/shutdown",
    summary=(
        """
        Stop neuron distributed simulation
        """
    ),
)
async def shutdown_simulation(
    org_id: str,
    project_id: str,
    job_id: str,
    token: str = Depends(verify_jwt),
) -> SimulationDetailsResponse:
    """
    Shutdown a running simulation identified by the given job ID (grouped simulations)
    """
    return await do_shutdown_simulation(
        token=token,
        task_id=job_id,
    )


@router.get(
    "/single-neuron/{org_id}/{project_id}",
    summary=(
        """
        Get all neuron simulations per project
        """
    ),
)
async def get_all_simulations_for_project(
    org_id: str,
    project_id: str,
    simulation_type: Optional[SimulationType] = None,
    page_offset: int = 0,
    page_size: int = 20,
    created_at_start: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    created_at_end: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    token: str = Depends(verify_jwt),
) -> PaginatedSimulationsResponse:
    """
    Retrieves all simulations associated with a specific project.

    This endpoint allows users to fetch all simulations for a given project,
    identified by the organization ID and project ID. The results are paginated,
    and users can filter the simulations based on their creation dates and simulation type.

    > **Note**:
    Simulation results (x, y points) are not included in the response to avoid
    excessive data transfer.
    """
    return fetch_all_simulations_of_project(
        token=token,
        org_id=org_id,
        project_id=project_id,
        sim_type=simulation_type,
        offset=page_offset,
        size=page_size,
        created_at_start=created_at_start,
        created_at_end=created_at_end,
    )


@router.get(
    "/single-neuron/{org_id}/{project_id}/{simulation_uri}",
    summary=(
        """
        Get simulation data
        """
    ),
)
async def get_simulation(
    org_id: str,
    project_id: str,
    simulation_uri: str = Path(
        ..., description="URL-encoded simulation URI (resource ID in nexus context)"
    ),
    token: str = Depends(verify_jwt),
) -> SimulationDetailsResponse:
    """
    Retrieves the results, status and metadata of a previously completed simulation.

    This endpoint allows to fetch the results and current status of a simulation
    identified by its URI. If the simulation is still in progress, the results will be
    returned as null. The organization ID and project ID are required to locate the
    specific simulation context.
    """
    return fetch_simulation_status_and_results(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_uri,
    )


@router.delete(
    "/single-neuron/{org_id}/{project_id}/{simulation_uri}",
    summary="Delete simulation",
)
async def delete_simulation(
    org_id: str,
    project_id: str,
    simulation_uri: str = Path(
        ..., description="URL-encoded simulation URI (resource ID in nexus context)"
    ),
    token: str = Depends(verify_jwt),
) -> DeprecateNexusResponse:
    """
    Deletes a simulation resource identified by its URI (resource ID in nexus context)

    This endpoint allows  to delete a specific simulation resource
    based on the provided organization ID, project ID, and simulation URI.
    Once deleted, the simulation resource will no longer be accessible.
    """
    return deprecate_simulation(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_uri,
    )
