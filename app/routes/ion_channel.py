from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from rq import Queue

from app.core.job import JobInfo
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep
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
    description="Run ion channel build",
    status_code=HTTPStatus.ACCEPTED,
)
async def run_ion_channel_build(
    request: Request,
    config: dict,
    project_context: ProjectContextDep,
    auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
    stream: bool = Query(False, description="Return streaming x-ndjson response"),
):
    return await run_ion_channel_build_service(
        config,
        request=request,
        job_queue=job_queue,
        project_context=project_context,
        auth=auth,
        stream=stream,
    )


@router.get("/build/jobs/{job_id}", tags=["ion-channel", "build"])
async def get_ion_channel_build_status(
    job_id: UUID,
    _project_context: ProjectContextDep,
    _auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM)),
) -> JobInfo:
    return await get_ion_channel_build_status_service(job_id=job_id, job_queue=job_queue)
