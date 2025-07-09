from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.domains.morphology import SynapsePlacementBody, SynapsePlacementResponse
from app.domains.simulation import (
    SingleNeuronSimulationConfig,
    StimulationItemResponse,
    StimulationPlotConfig,
)
from app.external.entitycore.service import ProjectContextDep
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_neuron.current_clamp_plot import (
    get_current_clamp_plot_data_stream,
)
from app.services.api.single_neuron.morphology import get_morphology_stream
from app.services.api.single_neuron.simulation import (
    run_simulation as run_simulation_service,
)
from app.services.api.single_neuron.synapse import (
    generate_synapses,
    validate_synapse_generation_formula,
)

router = APIRouter()


@router.post("/memodel/simulation/run", tags=["simulation", "memodel"])
def run_memodel_simulation(
    request: Request,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return run_simulation_service(
        model_id,
        config,
        auth=auth,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        realtime=True,
    )


@router.post("/single-neuron-synaptome/simulation/run", tags=["simulation", "memodel"])
def run_single_neuron_synaptome_simulation(
    request: Request,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return run_simulation_service(
        model_id,
        config,
        auth=auth,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        realtime=True,
    )


@router.post(
    "/single-neuron-synaptome/generate-synaptome-placement",
    response_model=SynapsePlacementResponse,
)
async def place_synapses(
    request: Request,
    params: SynapsePlacementBody,
    project_context: ProjectContextDep,
    model_id: UUID = Query(),
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
) -> StreamingResponse:
    return await generate_synapses(
        model_id,
        params,
        request=request,
        job_queue=job_queue,
        access_token=auth.access_token,
        project_context=project_context,
    )


@router.post(
    "/single-neuron-synaptome/synapse-formula/validate",
    response_model=bool,
)
def validate_synapse_formula(
    formula: str = Body(embed=True),
    _: Auth = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    return validate_synapse_generation_formula(formula=formula)  # type: ignore


@router.get("/memodel/morphology")
async def retrieve_morphology(
    model_id: UUID,
    request: Request,
    auth: Annotated[Auth, Depends(verify_jwt)],
    project_context: ProjectContextDep,
    job_queue: Annotated[Queue, Depends(queue_factory(JobQueue.HIGH))],
):
    return await get_morphology_stream(
        model_id,
        request=request,
        job_queue=job_queue,
        access_token=auth.access_token,
        project_context=project_context,
    )


@router.post(
    "/memodel/current-clamp-plot-data",
    response_model=List[StimulationItemResponse],
)
def retrieve_stimulation_plot(
    model_id: UUID,
    config: StimulationPlotConfig,
    request: Request,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return get_current_clamp_plot_data_stream(
        model_id,
        config,
        request=request,
        job_queue=job_queue,
        access_token=auth.access_token,
        project_context=project_context,
    )
