from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from obp_accounting_sdk.errors import InsufficientFundsError, BaseAccountingError
from obp_accounting_sdk.constants import ServiceSubtype
from http import HTTPStatus as status

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from bluenaas.infrastructure.accounting.session import accounting_session_factory
from bluenaas.infrastructure.kc.auth import Auth
from bluenaas.infrastructure.rq import Queue
from bluenaas.services.single_neuron_simulation import execute_single_neuron_simulation
from bluenaas.services.submit_simulaton import submit_background_simulation
from bluenaas.utils.rq_job import dispatch
from bluenaas.utils.streaming import x_ndjson_http_stream


def run_simulation(
    virtual_lab_id: str,
    project_id: str,
    request: Request,
    model_id: str,
    config: SingleNeuronSimulationConfig,
    job_queue: Queue,
    auth: Auth,
    realtime: bool = True,
    entitycore: bool = False,
):
    """
    Run a neuron simulation and optionally get results in realtime.
    If `realtime` query parameter is False only the simulation id is returned which can be used to retrieve status and result
    of simulation.

    Returns:
    --------
    If realtime is True - A StreamingResponse is returned which contains chunks of simulation data of type `SimulationItemResponse`

    If realtime is False - `BackgroundSimulationStatusResponse` is returned with simulation `id`. This `id` can be url-encoded and
    used to later query the status (and get result if any) of simulation.
    """

    accounting_subtype = (
        ServiceSubtype.SYNAPTOME_SIM
        if config.synaptome
        else ServiceSubtype.SINGLE_CELL_SIM
    )

    try:
        with accounting_session_factory.oneshot_session(
            subtype=accounting_subtype,
            proj_id=project_id,
            user_id=auth.decoded_token.sub,
            count=config.n_execs,
        ):
            if realtime is True:
                _job, stream = dispatch(
                    job_queue,
                    execute_single_neuron_simulation,
                    # job_args=(model_id, token, entitycore, project_context),
                    job_kwargs={
                        "org_id": virtual_lab_id,
                        "project_id": project_id,
                        "model_id": model_id,
                        "token": auth.token,
                        "config": config,
                        "realtime": realtime,
                        "entitycore": entitycore,
                    },
                )
                http_stream = x_ndjson_http_stream(request, stream)

                return StreamingResponse(http_stream, media_type="application/x-ndjson")

                # return execute_single_neuron_simulation(
                #     org_id=virtual_lab_id,
                #     project_id=project_id,
                #     model_id=model_id,
                #     token=auth.token,
                #     config=config,
                #     req_id=request.state.request_id,
                #     realtime=realtime,
                #     entitycore=entitycore,
                # )
            else:
                return submit_background_simulation(
                    job_queue=job_queue,
                    org_id=virtual_lab_id,
                    project_id=project_id,
                    model_self=model_id,
                    config=config,
                    token=auth.token,
                )
    except InsufficientFundsError as ex:
        logger.exception(f"Insufficient funds: {ex}")
        raise BlueNaasError(
            http_status_code=status.FORBIDDEN,
            error_code=BlueNaasErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the simulation",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.exception(f"Accounting service error: {ex}")
        raise BlueNaasError(
            http_status_code=status.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex
