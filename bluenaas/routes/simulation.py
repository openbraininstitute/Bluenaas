"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from loguru import logger
from bluenaas.domains.simulation import (
    SimulationDetailsResponse,
    SingleNeuronSimulationConfig,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.single_neuron_simulation import execute_single_neuron_simulation
from bluenaas.services.submit_simulaton import submit_background_simulation
from bluenaas.services.submit_simulaton.fetch_simulation_status_and_results import (
    fetch_simulation_status_and_results,
)

router = APIRouter(prefix="/simulation")


@router.post(
    "/single-neuron/{org_id}/{project_id}/run",
)
def run_simulation(
    request: Request,
    org_id: str,
    project_id: str,
    model_self: str,
    config: SingleNeuronSimulationConfig,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_jwt),
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
    if realtime is True:
        return execute_single_neuron_simulation(
            org_id=org_id,
            project_id=project_id,
            model_id=model_self,
            token=token,
            config=config,
            req_id=request.state.request_id,
            realtime=realtime,
        )
    else:
        return submit_background_simulation(
            org_id=org_id,
            project_id=project_id,
            model_self=model_self,
            config=config,
            token=token,
            background_tasks=background_tasks,
            request_id=request.state.request_id,
        )


@router.get(
    "/single-neuron/{org_id}/{project_id}/{simulation_id:path}",
    summary=(
        """
        Get results & status for a previously started simulation. 
        If simulation is not complete the results are null.
        `simulation_id` should be url encoded.
        """
    ),
)
async def get_simulation(
    org_id: str,
    project_id: str,
    simulation_id: str,
    token: str = Depends(verify_jwt),
) -> SimulationDetailsResponse:
    logger.debug(
        f"_____________________RECEIVED STATUS REQUEST_______________________-"
    )
    return fetch_simulation_status_and_results(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_id,
    )
