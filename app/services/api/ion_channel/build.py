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
from app.core.exceptions import AppError
from app.core.job import JobInfo
from app.domains.ion_channel.ion_channel import IonChannelBuildLaunch
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.accounting import make_accounting_reservation_async
from app.utils.rq_job import dispatch, get_job_info, run_async


async def run_ion_channel_build(
    config_id: UUID,
    *,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
) -> IonChannelBuildLaunch:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    config = await run_async(lambda: client.get_entity(config_id, entity_type=TaskConfig))
    if config.task_config_type != TaskConfigType.ion_channel_modeling__config:
        raise AppError(
            message="Not an ion channel modeling config",
            error_code=None,
            details=f"TaskConfig {config_id} is a {config.task_config_type}",
        )

    logger.info("Making accounting reservation for ion channel build")
    accounting_session = async_accounting_session_factory.oneshot_session(
        subtype=ServiceSubtype.ION_CHANNEL_BUILD,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=1,
        name=config.name,
    )

    await make_accounting_reservation_async(accounting_session)

    execution = await run_async(
        lambda: client.register_entity(
            TaskActivity(
                task_activity_type=TaskActivityType.ion_channel_modeling__execution,
                used=[config],
                start_time=datetime.now(UTC),
                status=ActivityStatus.pending,
            )
        )
    )
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

    job, _ = await dispatch(
        job_queue,
        JobFn.RUN_ION_CHANNEL_BUILD,
        timeout=60 * 10,  # 10 minutes
        job_args=(config_id,),
        on_start=on_start,
        on_success=on_success,
        on_failure=on_failure,
        job_kwargs={
            "execution_id": execution_id,
            "access_token": auth.access_token,
            "project_context": project_context,
        },
    )

    return IonChannelBuildLaunch(job_id=UUID(job.id), execution_id=execution_id)


async def get_ion_channel_build_status(job_id: UUID, *, job_queue: Queue) -> JobInfo:
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"message": "Job not found", "job_id": str(job_id)},
        )

    return await get_job_info(job)
