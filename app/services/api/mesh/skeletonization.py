from http import HTTPStatus
from uuid import UUID, uuid4

from entitysdk.common import ProjectContext
from fastapi import UploadFile
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from rq import Queue

from app.core.mesh.mesh import Mesh
from app.core.mesh.skeletonization_output import SkeletonizationOutput
from app.domains.mesh.skeletonization import SkeletonizationParams
from app.job import JobFn
from app.utils.file_upload import save_uploaded_file
from app.utils.rq_job import dispatch, run_async


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
        result_ttl=60 * 60 * 24 * 14,  # 14 days
        meta={"project_context": project_context},
        job_args=(mesh_id, params),
    )

    # TODO: dispatch cleanup job to remove output files after result_ttl

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


async def get_mesh_skeletonization_output_file(
    job_id: UUID, output_file_path: str, *, job_queue: Queue, project_context: ProjectContext
):
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=HTTPStatus.NOT_FOUND)

    output = SkeletonizationOutput(job_id)

    # Sanitize the output file path to prevent directory traversal attacks
    abs_output_file_path = (output.path / output_file_path).resolve()
    logger.info(f"Output file path: {abs_output_file_path}")
    if not abs_output_file_path.is_relative_to(output.path):
        return JSONResponse(
            {"error": "Invalid path: outside allowed directory"}, status_code=HTTPStatus.BAD_REQUEST
        )

    if not abs_output_file_path.exists():
        return JSONResponse({"error": "Output file not found"}, status_code=HTTPStatus.NOT_FOUND)

    return FileResponse(
        abs_output_file_path,
        media_type="application/octet-stream",
        filename=abs_output_file_path.name,
    )
