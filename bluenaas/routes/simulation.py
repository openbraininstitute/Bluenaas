import json
from http import HTTPStatus as status
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.model import Model
from bluenaas.core.simulation import Treat as SimulationTreat
from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot
from bluenaas.domains.simulation import (
    SimulationConfigBody,
    SimulationItemResponse,
    StimulationItemResponse,
    StimulationPlotConfig,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.utils.bearer_token import token_to_bearer

router = APIRouter(prefix="/simulation")


@router.post(
    "/run",
    response_model=List[SimulationItemResponse],
)
def run_simulation(
    model_id: str,
    config: SimulationConfigBody,
    token: str = Depends(verify_jwt),
):
    try:
        treat = SimulationTreat(
            model_id=model_id,
            config=config,
            token=token_to_bearer(token),
        )
        result = treat.run()

        def yield_chunks():
            for recording in result:
                yield json.dumps(recording)

        return StreamingResponse(
            yield_chunks(),
            media_type="application/x-ndjson",
        )
    except Exception as ex:
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="running simulation failed",
            details=ex.__str__(),
        ) from ex


@router.post(
    "/stimulation-plot",
    response_model=List[StimulationItemResponse],
)
def retrieve_stimulation_plot(
    model_id: str,
    config: StimulationPlotConfig,
    token: str = Depends(verify_jwt),
):
    try:
        model = Model(
            model_id=model_id,
            token=token_to_bearer(token),
        )
        model.build_model()

        stimulus_factory_plot = StimulusFactoryPlot(config, model.THRESHOLD_CURRENT)
        result_data = stimulus_factory_plot.apply_stim()
        return result_data
    except Exception as ex:
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="retrieving stimulation plot data failed",
            details=ex.__str__(),
        ) from ex
