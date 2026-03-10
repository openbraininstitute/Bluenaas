from http import HTTPStatus
from uuid import UUID

from entitysdk.common import ProjectContext
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from rq import Queue

from app.core.http_stream import x_ndjson_http_stream
from app.core.job import JobInfo
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.accounting import make_accounting_reservation_async
from app.utils.rq_job import dispatch, get_job_info, run_async


async def run_ion_channel_build(
    config: dict,
    *,
    request: Request,
    auth: Auth,
    project_context: ProjectContext,
    job_queue: Queue,
    stream: bool = False,
) -> JobInfo | StreamingResponse:
    logger.info("Making accounting reservation for ion channel build")
    accounting_session = async_accounting_session_factory.oneshot_session(
        subtype=ServiceSubtype.ION_CHANNEL_BUILD,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=1,
    )

    await make_accounting_reservation_async(accounting_session)

    async def on_start() -> None:
        await accounting_session.start()

    async def on_success() -> None:
        await accounting_session.finish()
        logger.info("Accounting session finished successfully")

    async def on_failure(exc_type: type[BaseException] | None) -> None:
        await accounting_session.finish(exc_type=exc_type)  # type: ignore

    job, job_stream = await dispatch(
        job_queue,
        JobFn.RUN_ION_CHANNEL_BUILD,
        timeout=60 * 10,  # 10 minutes
        job_args=(config,),
        on_start=on_start,
        on_success=on_success,
        on_failure=on_failure,
        job_kwargs={
            "access_token": auth.access_token,
            "project_context": project_context,
        },
    )

    if stream is True:
        http_stream = x_ndjson_http_stream(request, job_stream)
        return StreamingResponse(http_stream, media_type="application/x-ndjson")
    else:
        return await get_job_info(job)


async def get_ion_channel_build_status(job_id: UUID, *, job_queue: Queue) -> JobInfo:
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"message": "Job not found", "job_id": str(job_id)},
        )

    return await get_job_info(job)
