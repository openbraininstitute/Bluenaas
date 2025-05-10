from typing import List
from fastapi import APIRouter, Depends, Request
from uuid import UUID

from bluenaas.services.direct_current_plot import get_direct_current_plot_data
from bluenaas.infrastructure.kc.auth import verify_jwt, Auth
from bluenaas.domains.simulation import (
    StimulationItemResponse,
    StimulationPlotConfig,
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
    auth: Auth = Depends(verify_jwt),
):
    return get_direct_current_plot_data(
        model_id=str(model_id),
        config=config,
        token=auth.token,
        req_id=request.state.request_id,
        entitycore=True,
    )
