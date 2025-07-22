from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from entitysdk.models import Simulation, SimulationExecution, SimulationCampaign
from entitysdk.types import SimulationExecutionStatus
from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.config.settings import settings
from app.core.exceptions import AppError, AppErrorCode
from app.domains.circuit.simulation import SimulationParams
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.asyncio import run_async
from app.utils.rq_job import dispatch, get_job_data


async def run_circuit_simulation(
    simulation_id: UUID,
    *,
    request: Request,
    job_queue: Queue,
    project_context: ProjectContext,
    auth: Auth,
) -> StreamingResponse:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    simulation = await run_async(
        lambda: client.get_entity(
            simulation_id,
            entity_type=Simulation,
        )
    )

    simulation_campaign = await run_async(
        lambda: client.get_entity(
            simulation.simulation_campaign_id,
            entity_type=SimulationCampaign,
        )
    )

    # Estimate accounting task size in neuron seconds.
    _job, stream = await dispatch(
        job_queue,
        JobFn.GET_CIRCUIT_SIMULATION_PARAMS,
        job_args=(simulation_id,),
        job_kwargs={
            "circuit_id": simulation.entity_id,
            "access_token": auth.access_token,
            "project_context": project_context,
        },
    )
    sim_params_str = await get_job_data(stream)
    sim_params = SimulationParams.model_validate(sim_params_str)
    accounting_count = sim_params.num_cells * max(1, round(sim_params.tstop / 1000))

    logger.info(
        "Making accounting reservation for simulation run of "
        f"{sim_params.num_cells} neurons for {sim_params.tstop} ms. "
        f"Total accounting task size: {accounting_count} neuron seconds"
    )

    accounting_session = async_accounting_session_factory.oneshot_session(
        subtype=ServiceSubtype.SMALL_CIRCUIT_SIM,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=accounting_count,
        name=f"{simulation_campaign.name} - {simulation.name}",
    )

    try:
        await accounting_session.make_reservation()
        logger.info("Accounting reservation success")
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the simulation",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.warning(f"Accounting service error: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex

    simulation_execution_entity = await run_async(
        lambda: client.register_entity(
            SimulationExecution(
                used=[simulation],
                start_time=datetime.now(UTC),
                status=SimulationExecutionStatus.pending,
            )
        )
    )

    execution_id = simulation_execution_entity.id
    assert execution_id

    async def on_start() -> None:
        await accounting_session.start()

    async def on_success() -> None:
        await accounting_session.finish()
        logger.info("Accounting session finished successfully")

    async def on_failure(exc_type: type[BaseException] | None) -> None:
        await run_async(
            lambda: client.update_entity(
                entity_id=execution_id,
                entity_type=SimulationExecution,
                attrs_or_entity={
                    "end_time": datetime.now(UTC),
                    "status": SimulationExecutionStatus.error,
                },
            )
        )

        # TODO fix the exc_type type below.
        await accounting_session.finish(exc_type=exc_type)  # type: ignore

    _job, stream = await dispatch(
        job_queue,
        JobFn.RUN_CIRCUIT_SIMULATION,
        job_id=str(execution_id),
        job_args=(simulation_id,),
        job_kwargs={
            "circuit_id": simulation.entity_id,
            "execution_id": execution_id,
            "access_token": auth.access_token,
            "project_context": project_context,
        },
        on_failure=on_failure,
        on_start=on_start,
        on_success=on_success,
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(
        http_stream, media_type="application/x-ndjson", status_code=HTTPStatus.ACCEPTED
    )
