"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

import time
from fastapi import APIRouter, Depends, Path, Query, Response, status
from typing import Optional

from fastapi.params import Body

from bluenaas.config.settings import settings
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    SimulationResultItemResponse,
    SimulationType,
    PaginatedSimulationsResponse,
    StreamSimulationResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.infrastructure.celery import create_dummy_task
from bluenaas.services.simulation.run_simulation import run_simulation
from bluenaas.services.simulation.stop_simulation import stop_simulation
from bluenaas.services.simulation.submit_simulation import submit_simulation
from bluenaas.core.exceptions import BlueNaasError
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
    "/single-neuron/dummy",
    include_in_schema=settings.DEPLOYMENT_ENV != "production",
)
def dummy_simulation(
    tasks: int = Query(min=10, default=20),
):
    for i in range(tasks):
        create_dummy_task.apply_async()
        time.sleep(1)
        i += 1


@router.post(
    "/single-neuron/{org_id}/{project_id}/run-realtime",
    summary="Run simulation as background task and get realtime data",
)
def execute_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    autosave: Optional[bool] = Body(default=False, embed=True),
    token: str = Depends(verify_jwt),
) -> StreamSimulationResponse:
    """
    Initiates a simulation for a single neuron or synaptome model and returns a simulation results.

    Args:
        model_id (str): The identifier of the neuron model to simulate.
        org_id (str): The organization ID associated with the simulation request.
        project_id (str): The project ID associated with the simulation request.
        config (SingleNeuronSimulationConfig): Configuration settings for the simulation.
        token (str): The JWT token for authentication and authorization.

    Returns:
        SimulationResponse: A response containing the task ID and initial simulation information.

    Raises:
        HTTPException: If there is an issue with the simulation request.
    """
    return run_simulation(
        config=config,
        token=token,
        model_self=model_self,
        org_id=org_id,
        project_id=project_id,
        autosave=autosave,
    )


@router.post(
    "/single-neuron/{org_id}/{project_id}/{task_id}/stop",
    summary="stop simulation by task-id (only available when simulation started by the /run-realtime endpoint)",
)
async def kill_simulation(
    org_id: str,
    project_id: str,
    task_id: str,
    token: str = Depends(verify_jwt),
):
    return await stop_simulation(
        token=token,
        task_id=task_id,
    )


@router.post(
    "/single-neuron/{org_id}/{project_id}/launch",
    summary="Launch simulation to be run as a background task",
)
async def launch_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    response: Response,
    token: str = Depends(verify_jwt),
) -> SimulationResultItemResponse:
    try:
        result = submit_simulation(
            token=token,
            model_self=model_self,
            org_id=org_id,
            project_id=project_id,
            config=config,
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return result
    except BlueNaasError as e:
        response.status_code = e.http_status_code
        raise e
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise e


@router.get(
    "/single-neuron/{org_id}/{project_id}",
    description="Get all simulations for a project",
    summary=(
        """
        Returns all simulations in the provided project. 
        Please note, the data for simulations do not contain simulation results 
        (x, y points) to not bloat the response.
        """
    ),
)
async def get_all_simulations_for_project(
    org_id: str,
    project_id: str,
    simulation_type: Optional[SimulationType] = None,
    page_offset: int = 0,
    page_size: int = 20,
    token: str = Depends(verify_jwt),
) -> PaginatedSimulationsResponse:
    return fetch_all_simulations_of_project(
        token=token,
        org_id=org_id,
        project_id=project_id,
        sim_type=simulation_type,
        offset=page_offset,
        size=page_size,
    )


@router.get(
    "/single-neuron/{org_id}/{project_id}/{simulation_uri}",
    summary=(
        """
        Get results & status for a previously started simulation. 
        If simulation is not complete the results are null
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
) -> SimulationResultItemResponse:
    return fetch_simulation_status_and_results(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_uri,
    )


@router.delete(
    "/single-neuron/{org_id}/{project_id}/{simulation_uri}",
    summary="Delete simulation resource",
)
async def delete_simulation(
    org_id: str,
    project_id: str,
    simulation_uri: str = Path(
        ..., description="URL-encoded simulation URI (resource ID in nexus context)"
    ),
    token: str = Depends(verify_jwt),
) -> None:
    return deprecate_simulation(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_uri,
    )
