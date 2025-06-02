from typing import List
from fastapi import APIRouter, Depends, Request
from uuid import UUID

from bluenaas.services.current_clamp_plot import get_current_clamp_plot_data_stream
from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.domains.simulation import (
    StimulationItemResponse,
    StimulationPlotConfig,
)
from bluenaas.external.entitycore.service import ProjectContextDep


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
):
    return get_current_clamp_plot_data_stream(
        model_id=str(model_id),
        config=config,
        token=auth.token,
        req_id=request.state.request_id,
        entitycore=True,
        project_context=project_context,
    )
