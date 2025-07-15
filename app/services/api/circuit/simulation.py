from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from entitysdk.models import Simulation, SimulationExecution
from entitysdk.types import SimulationExecutionStatus
from fastapi import Request
from fastapi.responses import StreamingResponse
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue
from loguru import logger

from app.config.settings import settings
from app.core.exceptions import AppError, AppErrorCode
from app.infrastructure.kc.auth import Auth
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.asyncio import run_async
from app.utils.rq_job import dispatch


async def run_circuit_simulation(
    simulation_id: UUID,
    *,
    request: Request,
    job_queue: Queue,
    project_context: ProjectContext,
    auth: Auth,
) -> StreamingResponse:
    # TODO estimate number of CPUs for simulation
    num_cpus = 1

    accounting_session = async_accounting_session_factory.longrun_session(
        subtype=ServiceSubtype.SMALL_CIRCUIT_SIM,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        instances=num_cpus,
        instance_type="FARGATE",
        duration=60,  # defaults to one minute, TODO implement estimation logic
    )

    try:
        await accounting_session.make_reservation()
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

    simulation_execution = await run_async(
        lambda: client.register_entity(
            SimulationExecution(
                used=[simulation],
                start_time=datetime.now(UTC),
                status=SimulationExecutionStatus.pending,
            )
        )
    )

    async def on_start() -> None:
        await accounting_session.start()

    async def on_success() -> None:
        await accounting_session.finish()

    async def on_failure(exc_type: str) -> None:
        assert simulation_execution.id

        client.update_entity(
            entity_id=simulation_execution.id,
            entity_type=SimulationExecution,
            attrs_or_entity={
                "end_time": datetime.now(UTC),
                "status": SimulationExecutionStatus.error,
            },
        )

        await accounting_session.finish(exc_type=exc_type)

    _job, stream = await dispatch(
        job_queue,
        JobFn.RUN_CIRCUIT_SIMULATION,
        job_id=str(simulation_execution.id),
        job_kwargs={
            "circuit_id": simulation.entity_id,
            "simulation_id": simulation_id,
            "execution_id": simulation_execution.id,
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
