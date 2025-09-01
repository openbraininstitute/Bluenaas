from http.client import HTTPException
from entitysdk.common import ProjectContext
from fastapi import UploadFile
from fastapi.responses import JSONResponse
from http import HTTPStatus
from rq import Queue

from app.core.mesh.mesh import Mesh
from app.domains.mesh.skeletonization import SkeletonizationParams
from app.job import JobFn
from app.utils.file_upload import save_uploaded_file
from app.utils.rq_job import dispatch, run_async
from uuid import UUID, uuid4


async def run_mesh_skeletonization(
    mesh_file: UploadFile,
    params: SkeletonizationParams,
    *,
    job_queue: Queue,
    project_context: ProjectContext,
):
    if mesh_file.filename is None:
        raise ValueError("Uploaded file must have a filename")

    mesh_id = uuid4()

    mesh = Mesh(mesh_id)
    await save_uploaded_file(mesh_file, mesh.path / mesh_file.filename)
    mesh.init()

    job, _stream = await dispatch(
        job_queue,
        JobFn.RUN_MESH_SKELETONIZATION,
        job_id=str(mesh_id),
        timeout=60 * 60 * 3,  # 3 hours
        meta={"project_context": project_context},
        job_args=(mesh_id, params),
    )

    return JSONResponse({"id": job.id}, status_code=HTTPStatus.ACCEPTED)


async def get_mesh_skeletonization_status(
    job_id: UUID, *, job_queue: Queue, project_context: ProjectContext
):
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=HTTPStatus.NOT_FOUND)

    res = {
        "id": job.id,
        "status": job.get_status(),
        "queue_position": job.get_position(),
    }
    return JSONResponse(res, status_code=HTTPStatus.OK)
