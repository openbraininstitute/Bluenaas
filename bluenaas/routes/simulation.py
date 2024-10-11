"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

import time
from fastapi import APIRouter, Depends, Query, Response, status

from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    SimulationStatusResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.infrastructure.celery import create_dummy_task
from bluenaas.services.simulation.run_simulation import run_simulation
from bluenaas.services.simulation.stop_simulation import stop_simulation
from bluenaas.services.simulation.retrieve_simulation import retrieve_simulation
from bluenaas.services.simulation.submit_simulation import submit_simulation
from bluenaas.core.exceptions import BlueNaasError
from bluenaas.services.simulation.fetch_simulation_status_and_results import (
    fetch_simulation_status_and_results,
)

router = APIRouter(prefix="/simulation")


@router.post(
    "/single-neuron/dummy",
)
def dummy_simulation(
    tasks: int = Query(min=10, default=20),
):
    for i in range(tasks):
        create_dummy_task.apply_async()
        time.sleep(1)
        i += 1


@router.post(
    "/single-neuron/{org_id}/{project_id}/run",
)
def execute_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    token: str = Depends(verify_jwt),
):
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
    )


@router.post(
    "/single-neuron/{org_id}/{project_id}/{simulation_task_id}/stop",
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
    description="Launch simulation to be run as a background task",
)
async def launch_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    response: Response,
    token: str = Depends(verify_jwt),
) -> SimulationStatusResponse:
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
    "/single-neuron/{org_id}/{project_id}/{url_encoded_simulation_id}",
    description="Get results & status for a previously started simulation. If simulation is not complete then only the status of simulation is returned",
)
async def get_simulation_results(
    org_id: str,
    project_id: str,
    url_encoded_simulation_id: str,
    token: str = Depends(verify_jwt),
) -> SimulationStatusResponse:
    return fetch_simulation_status_and_results(
        token=token,
        org_id=org_id,
        project_id=project_id,
        encoded_simulation_id=url_encoded_simulation_id,
    )


@router.get(
    "/single-neuron/{org_id}/{project_id}/{simulation_id}/real-time-status",
)
def get_simulation(
    org_id: str,
    project_id: str,
    simulation_id: str,
    token: str = Depends(verify_jwt),
):
    return retrieve_simulation()
