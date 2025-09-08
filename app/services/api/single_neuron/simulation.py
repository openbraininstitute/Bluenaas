# TODO: refactor this module

from http import HTTPStatus
from uuid import UUID

from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.core.exceptions import AppError, AppErrorCode
from app.domains.simulation import SingleNeuronSimulationConfig
from app.infrastructure.accounting.session import accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


async def run_simulation(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    request: Request,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
    realtime: bool = True,
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
        ServiceSubtype.SYNAPTOME_SIM if config.synaptome else ServiceSubtype.SINGLE_CELL_SIM
    )

    try:
        with accounting_session_factory.oneshot_session(
            subtype=accounting_subtype,
            proj_id=project_context.project_id,
            user_id=auth.decoded_token.sub,
            count=len(config.expand()),
        ):
            _job, stream = await dispatch(
                job_queue,
                JobFn.RUN_SINGLE_NEURON_SIMULATION,
                job_args=(model_id, config),
                job_kwargs={
                    "project_context": project_context,
                    "access_token": auth.access_token,
                    "realtime": realtime,
                },
            )
            if realtime is True:
                http_stream = x_ndjson_http_stream(request, stream)
                return StreamingResponse(
                    http_stream, media_type="application/x-ndjson", status_code=HTTPStatus.ACCEPTED
                )
            else:
                return JSONResponse({"id": _job.id}, status_code=HTTPStatus.ACCEPTED)

    except InsufficientFundsError as ex:
        logger.exception(f"Insufficient funds: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the simulation",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.exception(f"Accounting service error: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex
