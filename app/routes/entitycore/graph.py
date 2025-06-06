from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from rq import Queue

from app.domains.simulation import (
    StimulationItemResponse,
    StimulationPlotConfig,
)
from app.external.entitycore.service import ProjectContextDep
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_cell.current_clamp_plot import (
    get_current_clamp_plot_data_stream,
)

router = APIRouter(prefix="/graph")


@router.post(
    "/direct-current-plot",
    response_model=List[StimulationItemResponse],
)
def retrieve_stimulation_plot(
    request: Request,
    model_id: UUID,
    config: StimulationPlotConfig,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return get_current_clamp_plot_data_stream(
        request=request,
        queue=job_queue,
        model_id=str(model_id),
        config=config,
        token=auth.token,
        entitycore=True,
        project_context=project_context,
    )
