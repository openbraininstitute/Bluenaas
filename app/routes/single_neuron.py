from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from rq import Queue

from app.domains.morphology import SynapsePlacementBody, SynapsePlacementResponse
from app.domains.neuron_model import MEModelCreateRequest, SingleNeuronSynaptomeCreateRequest
from app.domains.simulation import (
    SingleNeuronSimulationConfig,
    StimulationItemResponse,
    StimulationPlotConfig,
)
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep
from app.services.api.single_neuron.current_clamp_plot import (
    get_current_clamp_plot_data_response,
)
from app.services.api.single_neuron.morphology import get_morphology_service
from app.services.api.single_neuron.simulation import (
    run_simulation as run_simulation_service,
)
from app.services.api.single_neuron.single_neuron import (
    create_single_neuron_model as create_single_neuron_model_service,
)
from app.services.api.single_neuron.synaptome import (
    create_synaptome_model as create_synaptome_model_service,
)
from app.services.api.single_neuron.synaptome import (
    generate_synapses,
    validate_synapse_generation_formula,
)

router = APIRouter(prefix="/single-neuron")


@router.post("", tags=["single-neuron"], description="Create a single neuron model")
async def create_single_neuron_model(
    model: MEModelCreateRequest,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
):
    return await create_single_neuron_model_service(
        model, project_context=project_context, auth=auth, job_queue=job_queue
    )


@router.post(
    "/simulation/run",
    tags=["simulation", "single-neuron"],
    description="Run a single neuron simulation",
)
async def run_simulation(
    request: Request,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
):
    return await run_simulation_service(
        model_id,
        config,
        auth=auth,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        realtime=True,
    )


@router.post(
    "/synaptome", tags=["single-neuron"], description="Create a single neuron synaptome model"
)
async def create_synaptome_model(
    model: SingleNeuronSynaptomeCreateRequest,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
):
    return await create_synaptome_model_service(model, project_context=project_context, auth=auth)


@router.post(
    "/synaptome/generate",
    response_model=SynapsePlacementResponse,
    tags=["single-neuron", "synaptome"],
    description="Generate a synaptome for a single neuron model",
)
async def place_synapses(
    params: SynapsePlacementBody,
    project_context: ProjectContextDep,
    model_id: UUID = Query(),
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
) -> JSONResponse:
    return await generate_synapses(
        model_id,
        params,
        job_queue=job_queue,
        access_token=auth.access_token,
        project_context=project_context,
    )


@router.post(
    "/synaptome/validate-placement-formula",
    response_model=bool,
    tags=["single-neuron", "synaptome"],
    description="Validate a synapse placement formula",
)
def validate_synapse_formula(
    formula: str = Body(embed=True),
    _: Auth = Depends(verify_jwt),
) -> SynapsePlacementResponse:
    return validate_synapse_generation_formula(formula=formula)  # type: ignore


@router.get(
    "/morphology",
    tags=["single-neuron", "morphology"],
    description="Retrieve the morphology of a single neuron model",
)
async def retrieve_morphology(
    model_id: UUID,
    auth: Annotated[Auth, Depends(verify_jwt)],
    project_context: ProjectContextDep,
    job_queue: Annotated[Queue, Depends(queue_factory(JobQueue.HIGH))],
):
    return await get_morphology_service(
        model_id,
        job_queue=job_queue,
        access_token=auth.access_token,
        project_context=project_context,
    )


@router.post(
    "/current-clamp-plot-data",
    response_model=List[StimulationItemResponse],
    tags=["single-neuron", "stimuli"],
    description="Retrieve current clamp plot data for a single neuron model",
)
async def retrieve_stimulation_plot(
    model_id: UUID,
    config: StimulationPlotConfig,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return await get_current_clamp_plot_data_response(
        model_id,
        config,
        job_queue=job_queue,
        access_token=auth.access_token,
        project_context=project_context,
    )
