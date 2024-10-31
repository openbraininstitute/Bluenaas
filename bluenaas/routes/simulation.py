"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from fastapi import APIRouter, Depends, Request, BackgroundTasks

from bluenaas.domains.simulation import (
    BackgroundSimulationStatusResponse,
    SingleNeuronSimulationConfig,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.single_neuron_simulation import execute_single_neuron_simulation
from bluenaas.services.submit_simulaton import submit_background_simulation

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
        submit_background_simulation(
            org_id=org_id,
            project_id=project_id,
            model_self=model_id,
            config=config,
            token=token,
            background_tasks=background_tasks,
            request_id=request.state.request_id,
        )
