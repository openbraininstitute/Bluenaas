from http import HTTPStatus
from uuid import UUID, uuid4

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.models import EMCellMesh
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from rq import Queue

from app.config.settings import settings
from app.core.mesh.skeletonization_output import SkeletonizationOutput
from app.domains.mesh.skeletonization import SkeletonizationParams
from app.job import JobFn
from app.utils.rq_job import dispatch, run_async
from app.infrastructure.kc.auth import Auth


async def run_mesh_skeletonization(
    em_cell_mesh_id: UUID,
    params: SkeletonizationParams,
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

    execution_id = uuid4()

    job, _stream = await dispatch(
        job_queue,
        JobFn.RUN_MESH_SKELETONIZATION,
        timeout=60 * 60 * 3,  # 3 hours
        result_ttl=60 * 60 * 24 * 14,  # 14 days
        job_args=(em_cell_mesh_id, params),
        job_kwargs={
            "access_token": auth.access_token,
            "project_context": project_context,
            "execution_id": execution_id,
        },
    )

    return JSONResponse({"id": job.id}, status_code=HTTPStatus.ACCEPTED)


async def get_mesh_skeletonization_status(
    job_id: UUID, *, job_queue: Queue, project_context: ProjectContext
):
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=HTTPStatus.NOT_FOUND)

    status = job.get_status()
    output = SkeletonizationOutput(job_id)

    res = {
        "id": job.id,
        "status": status,
        "queue_position": job.get_position(),
        "output": None if status != "finished" else output.list_files(),
    }
    return JSONResponse(res, status_code=HTTPStatus.OK)
