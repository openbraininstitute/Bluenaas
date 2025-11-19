from uuid import UUID

from entitysdk import ProjectContext

from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationJobOutput,
    SkeletonizationUltraliserParams,
)
from app.domains.auth import Auth
from app.services.worker.mesh.skeletonization import run_mesh_skeletonization


def run(
    em_cell_mesh_id: UUID,
    input_params: SkeletonizationInputParams,
    ultraliser_params: SkeletonizationUltraliserParams,
    *,
    auth: Auth,
    execution_id: UUID,
    project_context: ProjectContext,
) -> SkeletonizationJobOutput:
    return run_mesh_skeletonization(
        em_cell_mesh_id,
        input_params,
        ultraliser_params,
        auth=auth,
        execution_id=execution_id,
        project_context=project_context,
    )
