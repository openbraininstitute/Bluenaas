from typing import List
from fastapi import APIRouter, Depends, Request
from rq import Queue

from app.infrastructure.rq import JobQueue, queue_factory
from app.services.api.single_cell.current_clamp_plot import (
    get_current_clamp_plot_data_stream,
)
from app.infrastructure.kc.auth import verify_jwt, Auth
from app.domains.simulation import (
    StimulationItemResponse,
    StimulationPlotConfig,
)


router = APIRouter(prefix="/graph")


@router.post(
    "/direct-current-plot",
    response_model=List[StimulationItemResponse],
)
async def retrieve_stimulation_plot(
    request: Request,
    model_self: str,
    config: StimulationPlotConfig,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.HIGH)),
):
    return await get_current_clamp_plot_data_stream(
        request=request,
        queue=job_queue,
        model_id=model_self,
        config=config,
        token=auth.access_token,
    )
