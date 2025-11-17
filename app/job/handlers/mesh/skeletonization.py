from uuid import UUID

from entitysdk import ProjectContext

from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationJobOutput,
    SkeletonizationUltraliserParams,
)
from app.services.worker.mesh.skeletonization import run_mesh_skeletonization


def run(
    em_cell_mesh_id: UUID,
    input_params: SkeletonizationInputParams,
    ultraliser_params: SkeletonizationUltraliserParams,
    *,
    access_token: str,
    execution_id: UUID,
    project_context: ProjectContext,
) -> SkeletonizationJobOutput:
    return run_mesh_skeletonization(
        em_cell_mesh_id,
        input_params,
        ultraliser_params,
        access_token=access_token,
        execution_id=execution_id,
        project_context=project_context,
    )
