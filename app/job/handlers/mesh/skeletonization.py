from uuid import UUID

from entitysdk import ProjectContext

from app.domains.mesh.skeletonization import SkeletonizationParams, SkeletonizationJobOutput
from app.services.worker.mesh.skeletonization import run_mesh_skeletonization


def run(
    em_cell_mesh_id: UUID,
    params: SkeletonizationParams,
    *,
    access_token: str,
    execution_id: UUID,
    project_context: ProjectContext,
) -> SkeletonizationJobOutput:
    return run_mesh_skeletonization(
        em_cell_mesh_id,
        params,
        access_token=access_token,
        execution_id=execution_id,
        project_context=project_context,
    )
