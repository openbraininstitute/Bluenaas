"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from fastapi import APIRouter, Depends, Request, Query, BackgroundTasks
from typing import Optional
from loguru import logger
from datetime import datetime
from obp_accounting_sdk.errors import InsufficientFundsError, BaseAccountingError
from obp_accounting_sdk.constants import ServiceSubtype
from http import HTTPStatus as status
from uuid import UUID

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.domains.simulation import (
    SimulationDetailsResponse,
    SingleNeuronSimulationConfig,
    SimulationType,
    PaginatedResponse,
)
from bluenaas.infrastructure.accounting.session import accounting_session_factory
from bluenaas.domains.nexus import DeprecateNexusResponse
from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.services.single_neuron_simulation import execute_single_neuron_simulation
from bluenaas.services.submit_simulaton import submit_background_simulation
from bluenaas.services.submit_simulaton.fetch_simulation_status_and_results import (
    fetch_simulation_status_and_results,
)
from bluenaas.services.submit_simulaton.deprecate_simulation import deprecate_simulation
from bluenaas.services.submit_simulaton.fetch_all_simulations_of_project import (
    fetch_all_simulations_of_project,
)
from bluenaas.routes import simulation

router = APIRouter(prefix="/simulation")


@router.post("/single-neuron/{virtual_lab_id}/{project_id}/run", tags=["simulation"])
def run_simulation(
    request: Request,
    virtual_lab_id: str,
    project_id: str,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    background_tasks: BackgroundTasks,
    auth: Auth = Depends(verify_jwt),
):
    return simulation.run_simulation(
        request=request,
        virtual_lab_id=virtual_lab_id,
        project_id=project_id,
        model_id=str(model_id),
        config=config,
        background_tasks=background_tasks,
        auth=auth,
        realtime=True,
        entitycore=True,
    )
