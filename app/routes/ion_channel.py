from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends
from rq import Queue

from app.core.job import JobInfo
from app.domains.task_config import TaskConfigRunLaunch, TaskConfigRunRequest
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep, UserAuthDep
from app.services.api.task_config import (
    ION_CHANNEL_BUILD,
    get_task_config_run_status,
    run_task_config,
)

router = APIRouter(prefix="/ion-channel")


@router.post(
    "/build/run",
    tags=["ion-channel", "build"],
    description="Fit the ion channel model of an ion_channel_modeling__config TaskConfig",
    status_code=HTTPStatus.ACCEPTED,
)
async def run_ion_channel_build(
    body: TaskConfigRunRequest,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
) -> TaskConfigRunLaunch:
    return await run_task_config(
        body.config_id,
        ION_CHANNEL_BUILD,
        job_queue=job_queue,
        project_context=project_context,
        auth=auth,
    )


@router.get("/build/jobs/{job_id}", tags=["ion-channel", "build"])
async def get_ion_channel_build_status(
    job_id: UUID,
    _project_context: ProjectContextDep,
    _auth: UserAuthDep,
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
) -> JobInfo:
    return await get_task_config_run_status(job_id=job_id, job_queue=job_queue)
