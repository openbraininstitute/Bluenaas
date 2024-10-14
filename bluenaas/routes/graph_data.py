from typing import List
from fastapi import APIRouter, Depends, Request

from bluenaas.services.direct_current_plot import get_direct_current_plot_data
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.domains.simulation import (
    StimulationItemResponse,
    StimulationPlotConfig,
)


router = APIRouter(prefix="/graph")


@router.post(
    "/direct-current-plot",
    response_model=List[StimulationItemResponse],
    summary="Retrieve current stimulation plot data",
)
def retrieve_stimulation_plot(
    request: Request,
    model_id: str,
    config: StimulationPlotConfig,
    token: str = Depends(verify_jwt),
):
    return get_direct_current_plot_data(
        model_id=model_id,
        config=config,
        token=token,
        req_id=request.state.request_id,
    )
