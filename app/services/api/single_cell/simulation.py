# TODO: refactor this module

from http import HTTPStatus as status

from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.core.exceptions import BlueNaasError, BlueNaasErrorCode
from app.domains.nexus import FullNexusSimulationResource
from app.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from app.infrastructure.accounting.session import accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.rq_job import dispatch, wait_for_job
from app.utils.simulation import convert_to_simulation_response
from app.utils.api.streaming import x_ndjson_http_stream


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
                    JobFn.RUN_SINGLE_CELL_SIMULATION,
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
            else:
                return _submit_background_simulation(
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


def _submit_background_simulation(
    job_queue: Queue,
    org_id: str,
    project_id: str,
    model_self: str,
    config: SingleNeuronSimulationConfig,
    token: str,
):
    # (
    #     me_model_self,
    #     synaptome_model_self,
    #     _stimulus_plot_data,
    #     sim_response,
    #     simulation_resource,
    # ) = setup_simulation_resources(
    #     token,
    #     model_self,
    #     org_id,
    #     project_id,
    #     config,
    # )

    setup_job = job_queue.enqueue(
        JobFn.SETUP_SIMULATION_RESOURCES,
        token,
        model_self,
        org_id,
        project_id,
        config,
    )

    (
        me_model_self,
        synaptome_model_self,
        _stimulus_plot_data,
        sim_response,
        simulation_resource,
    ) = wait_for_job(setup_job)

    logger.debug(
        f"Submitting simulation task for resource {simulation_resource['_self']}"
    )
    # Step 2: Add background task to process simulation
    job_queue.enqueue(
        JobFn.RUN_SINGLE_CELL_SIMULATION,
        kwargs={
            "org_id": org_id,
            "project_id": project_id,
            "model_id": model_self,
            "token": token,
            "config": config,
            "realtime": False,
            "simulation_resource_self": sim_response["_self"],
        },
    )

    # Step 3: Return simulation status to user
    return convert_to_simulation_response(
        simulation_uri=simulation_resource["@id"],
        simulation_resource=FullNexusSimulationResource.model_validate(
            simulation_resource,
        ),
        me_model_self=me_model_self,
        synaptome_model_self=synaptome_model_self,
        simulation_config=config,
        results=None,
    )
