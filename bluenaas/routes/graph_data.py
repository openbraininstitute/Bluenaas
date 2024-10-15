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
    model_self: str,
    config: StimulationPlotConfig,
    token: str = Depends(verify_jwt),
):
    """
    Retrieves data for current stimulation plots based on the specified model and configuration.

    Args:

        model_self (str):
            The unique identifier for the model for which the stimulation plot data is requested.
            This should correspond to a valid model self in nexus's context.

        config (StimulationPlotConfig):
            Configuration settings that define how the stimulation plot should be generated.
            This includes parameters such as stimulation amplitudes and stimulus_protocol.


    Returns:

        List[StimulationItemResponse]:
            A list of stimulation plot data items, where each item contains information about a
            specific stimulation instance, including its parameters and results.

    Raises:

        HTTPException:
            An HTTP exception may be raised for issues.

    """
    return get_direct_current_plot_data(
        model_self=model_self,
        config=config,
        token=token,
        req_id=request.state.request_id,
    )
