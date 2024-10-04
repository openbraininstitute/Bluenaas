"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from fastapi import APIRouter, Depends
from bluenaas.domains.simulation import SingleNeuronSimulationConfig
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.simulation.run_simulation import run_simulation
from bluenaas.services.simulation.stop_simulation import stop_simulation
from bluenaas.services.simulation.retrieve_simulation import retrieve_simulation

router = APIRouter(prefix="/simulation")


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
    Initiates a simulation for a single neuron or synaptome model and returns a simulaton results.

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


@router.get(
    "/single-neuron/{org_id}/{project_id}/{simulation_id}",
)
def get_simulation(
    org_id: str,
    project_id: str,
    simulation_id: str,
    token: str = Depends(verify_jwt),
):
    return retrieve_simulation()
