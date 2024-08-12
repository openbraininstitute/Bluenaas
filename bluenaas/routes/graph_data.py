from http import HTTPStatus as status
from typing import List

from fastapi import APIRouter, Depends

from bluenaas.core.model import model_factory
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot
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
    model_id: str,
    config: StimulationPlotConfig,
    token: str = Depends(verify_jwt),
):
    try:
        model = model_factory(
            model_id=model_id,
            bearer_token=token,
        )

        stimulus_factory_plot = StimulusFactoryPlot(
            config,
            model.THRESHOLD_CURRENT,
        )
        result_data = stimulus_factory_plot.apply_stim()
        return result_data
    except Exception as ex:
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="retrieving stimulation plot data failed",
            details=ex.__str__(),
        ) from ex
