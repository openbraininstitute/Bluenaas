from datetime import UTC, datetime
from http import HTTPStatus
from typing import Dict, List
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from entitysdk.models import Simulation, SimulationCampaign, SimulationExecution
from entitysdk.types import SimulationExecutionStatus
from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from obp_accounting_sdk import AsyncOneshotSession
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.config.settings import settings
from app.core.exceptions import AppError, AppErrorCode
from app.core.http_stream import x_ndjson_http_stream
from app.domains.circuit.simulation import SimulationParams
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.infrastructure.rq import JobQueue, get_queue
from app.job import JobFn
from app.utils.asyncio import interleave_async_iterators, run_async
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
        timeout=60 * 60,  # one hour
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(
        http_stream, media_type="application/x-ndjson", status_code=HTTPStatus.ACCEPTED
    )


async def _get_sim_params_map(
    simulation_ids: List[UUID],
    *,
    auth: Auth,
    project_context: ProjectContext,
) -> Dict[UUID, SimulationParams]:
    _job, stream = await dispatch(
        get_queue(JobQueue.HIGH),
        JobFn.GET_CIRCUIT_SIMULATION_BATCH_PARAMS_MAP,
        job_args=(simulation_ids,),
        job_kwargs={
            "access_token": auth.access_token,
            "project_context": project_context,
        },
    )
    sim_params_map_str = await get_job_data(stream)
    sim_params_map: Dict[UUID, SimulationParams] = {
        UUID(k): SimulationParams.model_validate(v) for k, v in sim_params_map_str.items()
    }
    return sim_params_map


async def _fetch_sim(simulation_id: UUID, client: Client) -> Simulation:
    return await run_async(lambda: client.get_entity(simulation_id, entity_type=Simulation))


async def _fetch_sim_campaign(sim_campaign_id: UUID, client: Client) -> SimulationCampaign:
    return await run_async(
        lambda: client.get_entity(sim_campaign_id, entity_type=SimulationCampaign)
    )


async def _create_sim_exec_entity(sim: Simulation, client: Client) -> SimulationExecution:
    return await run_async(
        lambda: client.register_entity(
            SimulationExecution(
                used=[sim],
                start_time=datetime.now(UTC),
                status=SimulationExecutionStatus.pending,
            )
        )
    )


async def _cancel_reservations(
    accounting_session_map: Dict[UUID, AsyncOneshotSession],
) -> None:
    for session in accounting_session_map.values():
        # If the "start" method was not called - executing "finish" will cancel reservation.
        await session.finish()


async def run_circuit_simulation_batch(
    simulation_ids: List[UUID],
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

    sim_map = {sim_id: await _fetch_sim(sim_id, client) for sim_id in simulation_ids}

    sim_campaign_ids = list(set([sim.simulation_campaign_id for sim in sim_map.values()]))
    sim_campaign_map = {
        sim_campaign_id: await _fetch_sim_campaign(sim_campaign_id, client)
        for sim_campaign_id in sim_campaign_ids
    }

    sim_params_map = await _get_sim_params_map(
        simulation_ids,
        auth=auth,
        project_context=project_context,
    )

    # TODO Next below

    accounting_session_map: Dict[UUID, AsyncOneshotSession] = {}
    try:
        for sim_id in simulation_ids:
            sim = sim_map[sim_id]
            sim_campaign = sim_campaign_map[sim.simulation_campaign_id]

            sim_params = sim_params_map[sim_id]
            accounting_count = sim_params.num_cells * max(1, round(sim_params.tstop / 1000))

            accounting_session = async_accounting_session_factory.oneshot_session(
                subtype=ServiceSubtype.SMALL_CIRCUIT_SIM,
                proj_id=project_context.project_id,
                user_id=auth.decoded_token.sub,
                count=accounting_count,
                name=f"{sim_campaign.name} - {sim.name}",
            )

            logger.info(
                "Making accounting reservation for simulation run of "
                f"{sim_params.num_cells} neurons for {sim_params.tstop} ms. "
                f"Total accounting task size: {accounting_count} neuron seconds"
            )

            await accounting_session.make_reservation()

            accounting_session_map[sim_id] = accounting_session  # type: ignore
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        await _cancel_reservations(accounting_session_map)
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the simulation",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.warning(f"Accounting service error: {ex}")
        await _cancel_reservations(accounting_session_map)
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex

    job_streams = []

    for sim in sim_map.values():
        simulation_execution_entity = await _create_sim_exec_entity(sim, client)
        exec_id = simulation_execution_entity.id
        accounting_session = accounting_session_map[sim.id]  # type: ignore

        async def on_start() -> None:
            await accounting_session.start()
            logger.info("Accounting session started successfully")

        async def on_success() -> None:
            await accounting_session.finish()
            logger.info("Accounting session finished successfully")

        async def on_failure(exc_type: type[BaseException] | None) -> None:
            await run_async(
                lambda: client.update_entity(
                    entity_id=exec_id,  # type: ignore
                    entity_type=SimulationExecution,
                    attrs_or_entity={
                        "end_time": datetime.now(UTC),
                        "status": SimulationExecutionStatus.error,
                    },
                )
            )

            # TODO fix the exc_type type below.
            await accounting_session.finish(exc_type=exc_type)  # type: ignore
            logger.info("Accounting session with provided exception finished successfully")

        _job, stream = await dispatch(
            job_queue,
            JobFn.RUN_CIRCUIT_SIMULATION,
            job_id=str(exec_id),
            job_args=(sim.id,),
            job_kwargs={
                "circuit_id": sim.entity_id,
                "execution_id": exec_id,
                "access_token": auth.access_token,
                "project_context": project_context,
            },
            stream_ctx={
                "circuit_id": sim.entity_id,
                "execution_id": exec_id,
                "simulation_id": sim.id,
            },
            on_failure=on_failure,
            on_start=on_start,
            on_success=on_success,
        )
        job_streams.append(stream)

    stream = interleave_async_iterators(job_streams)
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(
        http_stream, media_type="application/x-ndjson", status_code=HTTPStatus.ACCEPTED
    )
