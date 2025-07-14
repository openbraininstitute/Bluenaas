# TODO: refactor this module

from http import HTTPStatus as status
from uuid import UUID

from entitysdk.common import ProjectContext
from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.core.exceptions import BlueNaasError, BlueNaasErrorCode
from app.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from app.infrastructure.accounting.session import accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch, wait_for_job


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
        ServiceSubtype.SYNAPTOME_SIM
        if config.synaptome
        else ServiceSubtype.SINGLE_CELL_SIM
    )

    try:
        with accounting_session_factory.oneshot_session(
            subtype=accounting_subtype,
            proj_id=project_context.project_id,
            user_id=auth.decoded_token.sub,
            count=config.n_execs,
        ):
            if realtime is True:
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
                http_stream = x_ndjson_http_stream(request, stream)

                return StreamingResponse(http_stream, media_type="application/x-ndjson")
            else:
                return _submit_background_simulation(
                    job_queue=job_queue,
                    project_context=project_context,
                    model_id=model_id,
                    config=config,
                    access_token=auth.access_token,
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


async def _submit_background_simulation(
    job_queue: Queue,
    project_context: ProjectContext,
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    access_token: str,
):
    setup_job = job_queue.enqueue(
        JobFn.SETUP_SINGLE_NEURON_SIMULATION_RESOURCES,
        access_token,
        model_id,
        project_context,
        config,
    )

    (
        me_model_self,
        synaptome_model_self,
        _stimulus_plot_data,
        sim_response,
        simulation_resource,
    ) = await wait_for_job(setup_job)

    logger.debug(
        f"Submitting simulation task for resource {simulation_resource['_self']}"
    )
    # Step 2: Add background task to process simulation
    job_queue.enqueue(
        JobFn.RUN_SINGLE_NEURON_SIMULATION,
        kwargs={
            "project_context": project_context,
            "model_id": model_id,
            "token": access_token,
            "config": config,
            "realtime": False,
            "simulation_resource_self": sim_response["_self"],
        },
    )
