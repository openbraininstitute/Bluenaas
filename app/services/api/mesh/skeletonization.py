from datetime import datetime
from http import HTTPStatus
from uuid import UUID, uuid4

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.models import EMCellMesh
from fastapi.responses import JSONResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.config.settings import settings
from app.core.exceptions import AppError, AppErrorCode
from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationUltraliserParams,
)
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.rq_job import dispatch, run_async


async def run_mesh_skeletonization(
    em_cell_mesh_id: UUID,
    input_params: SkeletonizationInputParams,
    ultraliser_params: SkeletonizationUltraliserParams,
    *,
    auth: Auth,
    job_queue: Queue,
    project_context: ProjectContext,
):
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    em_cell_mesh = await run_async(
        lambda: client.get_entity(
            em_cell_mesh_id,
            entity_type=EMCellMesh,
        )
    )

    logger.info("Making accounting reservation for neuron mesh skeletonization")

    accounting_session = async_accounting_session_factory.oneshot_session(
        subtype=ServiceSubtype.NEURON_MESH_SKELETONIZATION,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=1,
        name=em_cell_mesh.name,
    )

    try:
        await accounting_session.make_reservation()
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the neuron mesh skeletonization",
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

    async def on_start() -> None:
        await accounting_session.start()
        logger.debug("Accounting session started")

    async def on_success() -> None:
        await accounting_session.finish()
        logger.debug("Accounting session finished successfully")

    async def on_failure(exc_type: type[BaseException] | None) -> None:
        await accounting_session.finish(exc_type=exc_type)  # type: ignore
        logger.debug("Accounting session finished successfully with provided job exception")

    execution_id = uuid4()

    job, _stream = await dispatch(
        job_queue,
        JobFn.RUN_MESH_SKELETONIZATION,
        timeout=60 * 60 * 3,  # 3 hours
        result_ttl=60 * 60 * 24 * 30,  # 30 days
        job_args=(em_cell_mesh_id, input_params, ultraliser_params),
        job_kwargs={
            "access_token": auth.access_token,
            "project_context": project_context,
            "execution_id": execution_id,
        },
        on_start=on_start,
        on_success=on_success,
        on_failure=on_failure,
    )

    return JSONResponse({"id": job.id}, status_code=HTTPStatus.ACCEPTED)


def _format_date(date: datetime | None) -> str | None:
    return date.isoformat() if date else None


async def get_mesh_skeletonization_status(
    job_id: UUID, *, job_queue: Queue, project_context: ProjectContext
):
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=HTTPStatus.NOT_FOUND)

    status = job.get_status(refresh=False)
    job_position = await run_async(lambda: job.get_position())

    res = {
        "id": str(job.id),
        "created_at": _format_date(job.created_at),
        "enqueued_at": _format_date(job.enqueued_at),
        "started_at": _format_date(job.started_at),
        "ended_at": _format_date(job.ended_at),
        "status": status,
        "queue_position": job_position,
        "error": job.exc_info,
        "output": job.result.model_dump(mode="json") if job.result else None,
    }

    return JSONResponse(res, status_code=HTTPStatus.OK)
