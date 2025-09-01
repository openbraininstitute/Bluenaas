from uuid import UUID

import ultraliser
from loguru import logger

from app.core.mesh.mesh import Mesh
from app.core.mesh.skeletonization_output import SkeletonizationOutput
from app.domains.mesh.skeletonization import SkeletonizationParams
from app.utils.safe_process import SafeProcessExecutor


def run_mesh_skeletonization(
    mesh_id: UUID,
    params: SkeletonizationParams,
) -> None:
    mesh = Mesh(mesh_id)
    mesh.init()

    output = SkeletonizationOutput(mesh_id)

    params_dict = {k: v for k, v in params.model_dump().items() if v is not None}

    logger.info(f"Running skeletonization for mesh {mesh_id}")
    logger.info(f"Parameters: {params_dict}")

    executor = SafeProcessExecutor()

    try:
        result = executor.execute(
            target_func=ultraliser.skeletonizeNeuronMesh,
            args=(mesh.file_path, output.path),
            kwargs=params_dict,
        )

        logger.info(f"Process logs:\n{result.logs}")
    except SafeProcessRuntimeError as e:
        logger.error(f"Skeletonization failed: {e}")
        raise
    finally:
        mesh.cleanup()
