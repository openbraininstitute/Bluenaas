"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from bluenaas.external.entitycore.service import ProjectContextDep
from bluenaas.infrastructure.kc.auth import Auth, verify_jwt
from bluenaas.services.simulation import run_simulation as run_simulation_service

router = APIRouter(prefix="/simulation")


@router.post("/single-neuron/{virtual_lab_id}/{project_id}/run", tags=["simulation"])
def run_simulation(
    request: Request,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    background_tasks: BackgroundTasks,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
):
    return run_simulation_service(
        request=request,
        virtual_lab_id=str(project_context.virtual_lab_id),
        project_id=str(project_context.project_id),
        model_id=str(model_id),
        config=config,
        background_tasks=background_tasks,
        auth=auth,
        realtime=True,
        entitycore=True,
    )
