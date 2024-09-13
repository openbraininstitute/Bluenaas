"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from typing import List

from fastapi import APIRouter, Depends, Request

from bluenaas.domains.simulation import (
    SimulationItemResponse,
    SingleNeuronSimulationConfig,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.services.single_neuron_simulation import execute_single_neuron_simulation


router = APIRouter(prefix="/simulation")


@router.post(
    "/single-neuron/run",
    response_model=List[SimulationItemResponse],
)
def run_simulation(
    request: Request,
    model_id: str,
    config: SingleNeuronSimulationConfig,
    token: str = Depends(verify_jwt),
):
    return execute_single_neuron_simulation(
        model_id=model_id,
        token=token,
        config=config,
        req_id=request.state.request_id,
    )
