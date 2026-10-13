from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends
from rq import Queue

from app.core.job import JobInfo
from app.domains.ion_channel.ion_channel import IonChannelBuildLaunch, IonChannelBuildRequest
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep, UserAuthDep
from app.services.api.ion_channel.build import (
    get_ion_channel_build_status as get_ion_channel_build_status_service,
)
from app.services.api.ion_channel.build import (
    run_ion_channel_build as run_ion_channel_build_service,
)

router = APIRouter(prefix="/ion-channel")


@router.post(
    "/build/run",
    tags=["ion-channel", "build"],
    description="Fit the ion channel model of an ion_channel_modeling__config TaskConfig",
    status_code=HTTPStatus.ACCEPTED,
)
async def run_ion_channel_build(
    body: IonChannelBuildRequest,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
) -> IonChannelBuildLaunch:
    return await run_ion_channel_build_service(
        body.config_id,
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
    return await get_ion_channel_build_status_service(job_id=job_id, job_queue=job_queue)
