from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from rq import Queue

from app.domains.mesh.skeletonization import SkeletonizationParams
from app.infrastructure.kc.auth import Auth, verify_jwt
from app.infrastructure.rq import JobQueue, queue_factory
from app.routes.dependencies import ProjectContextDep
from app.services.api.mesh.skeletonization import (
    get_mesh_skeletonization_output_file as get_mesh_skeletonization_output_file_service,
)
from app.services.api.mesh.skeletonization import (
    get_mesh_skeletonization_status as get_mesh_skeletonization_status_service,
)
from app.services.api.mesh.skeletonization import (
    run_mesh_skeletonization as run_mesh_skeletonization_service,
)

router = APIRouter(prefix="/mesh")


@router.post("/skeletonization/run", tags=["mesh", "skeletonization"])
async def run_mesh_skeletonization(
    project_context: ProjectContextDep,
    _auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MESH_SKELETONIZATION)),
    mesh_file: UploadFile = File(...),
    params: SkeletonizationParams = Depends(),
):
    return await run_mesh_skeletonization_service(
        mesh_file=mesh_file,
        params=params,
        job_queue=job_queue,
        project_context=project_context,
    )


@router.get("/skeletonization/jobs/{job_id}", tags=["mesh", "skeletonization"])
async def get_mesh_skeletonization_status(
    job_id: UUID,
    project_context: ProjectContextDep,
    _auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MESH_SKELETONIZATION)),
):
    return await get_mesh_skeletonization_status_service(
        job_id=job_id, project_context=project_context, job_queue=job_queue
    )


@router.get(
    "/skeletonization/jobs/{job_id}/output/{output_file_path:path}",
    tags=["mesh", "skeletonization"],
)
async def get_mesh_skeletonization_output_file(
    job_id: UUID,
    output_file_path: str,
    project_context: ProjectContextDep,
    _auth: Auth = Depends(verify_jwt),
    job_queue: Queue = Depends(queue_factory(JobQueue.MESH_SKELETONIZATION)),
):
    return await get_mesh_skeletonization_output_file_service(
        job_id=job_id,
        output_file_path=output_file_path,
        project_context=project_context,
        job_queue=job_queue,
    )
