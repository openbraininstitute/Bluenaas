from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.models import TaskActivity, TaskConfig
from entitysdk.types import ActivityStatus, TaskActivityType, TaskConfigType
from fastapi import HTTPException
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from rq import Queue

from app.config.settings import settings
from app.constants import MAX_JOB_TIMEOUT
from app.core.exceptions import AppError
from app.core.job import JobInfo
from app.domains.task_config import TaskConfigRunLaunch
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.accounting import make_accounting_reservation_async
from app.utils.rq_job import dispatch, get_job_info, run_async


@dataclass(frozen=True)
class TaskConfigRun:
    """How Bluenaas runs the obi-one task of one kind of single TaskConfig."""

    name: str
    # obi-one TaskType value; the API process does not import obi-one
    task_type: str
    config_type: TaskConfigType
    activity_type: TaskActivityType
    service_subtype: ServiceSubtype
    timeout: int


ION_CHANNEL_BUILD = TaskConfigRun(
    name="ion channel modeling",
    task_type="ion_channel_fitting",
    config_type=TaskConfigType.ion_channel_modeling__config,
    activity_type=TaskActivityType.ion_channel_modeling__execution,
    service_subtype=ServiceSubtype.ION_CHANNEL_BUILD,
    timeout=MAX_JOB_TIMEOUT,
)

MEMODEL_BUILD = TaskConfigRun(
    name="ME-model build",
    task_type="memodel_build",
    config_type=TaskConfigType.memodel_build__config,
    activity_type=TaskActivityType.memodel_build__execution,
    service_subtype=ServiceSubtype.SINGLE_CELL_BUILD,
    timeout=40 * 60,
)


async def run_task_config(
    config_id: UUID,
    run: TaskConfigRun,
    *,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
) -> TaskConfigRunLaunch:
    """Reserve credits, register a pending execution and queue the task of a single config.

    The worker sets the execution running, then done or error. The job callbacks settle the
    credits, and fail the execution when the worker dies before it can.
    """
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    config = await run_async(lambda: client.get_entity(config_id, entity_type=TaskConfig))
    if config.task_config_type != run.config_type:
        raise AppError(
            message=f"Not an {run.name} config",
            error_code=None,
            details=f"TaskConfig {config_id} is a {config.task_config_type}",
        )

    logger.info(f"Making accounting reservation for {run.name}")
    accounting_session = async_accounting_session_factory.oneshot_session(
        subtype=run.service_subtype,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=1,
        name=config.name,
    )

    await make_accounting_reservation_async(accounting_session)

    try:
        execution = await run_async(
            lambda: client.register_entity(
                TaskActivity(
                    task_activity_type=run.activity_type,
                    used=[config],
                    start_time=datetime.now(UTC),
                    status=ActivityStatus.pending,
                )
            )
        )
    except Exception as exc:
        await accounting_session.finish(exc_type=type(exc))
        raise
    execution_id = execution.id
    assert execution_id

    async def on_start() -> None:
        await accounting_session.start()

    async def on_success() -> None:
        await accounting_session.finish()
        logger.info("Accounting session finished successfully")

    async def on_failure(exc_type: type[BaseException] | None) -> None:
        await accounting_session.finish(exc_type=exc_type)
        # The worker marks the execution as failed too, but not when it dies before it can.
        await run_async(
            lambda: client.update_entity(
                entity_id=execution_id,
                entity_type=TaskActivity,
                attrs_or_entity={"end_time": datetime.now(UTC), "status": ActivityStatus.error},
            )
        )

    try:
        job, _ = await dispatch(
            job_queue,
            JobFn.RUN_TASK_CONFIG,
            timeout=run.timeout,
            job_args=(run.task_type, config_id),
            on_start=on_start,
            on_success=on_success,
            on_failure=on_failure,
            job_kwargs={
                "execution_id": execution_id,
                "access_token": auth.access_token,
                "project_context": project_context,
            },
        )
    except Exception as exc:
        await on_failure(type(exc))
        raise

    return TaskConfigRunLaunch(job_id=UUID(job.id), execution_id=execution_id)


async def get_task_config_run_status(job_id: UUID, *, job_queue: Queue) -> JobInfo:
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"message": "Job not found", "job_id": str(job_id)},
        )

    return await get_job_info(job)
