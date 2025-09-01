from uuid import UUID

from app.domains.mesh.skeletonization import SkeletonizationParams
from app.services.worker.mesh.skeletonization import (
    run_mesh_skeletonization,
)


def run(
    mesh_id: UUID,
    params: SkeletonizationParams,
) -> None:
    run_mesh_skeletonization(
        mesh_id=mesh_id,
        params=params,
    )
