from uuid import UUID

from entitysdk import Client, ProjectContext
from loguru import logger

from app.config.settings import settings
from app.core.mesh.skeletonization import Skeletonization
from app.domains.mesh.skeletonization import SkeletonizationJobOutput, SkeletonizationParams
from app.utils.safe_process import SafeProcessRuntimeError


def run_mesh_skeletonization(
    em_cell_mesh_id: UUID,
    params: SkeletonizationParams,
    *,
    execution_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> SkeletonizationJobOutput:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    try:
        skeletonization = Skeletonization(
            em_cell_mesh_id,
            params,
            client=client,
            execution_id=execution_id,
        )

        skeletonization.init()
        skeletonization.run()
        morphology = skeletonization.output.upload()
        skeletonization.output.cleanup()
    except SafeProcessRuntimeError as e:
        logger.error(f"Skeletonization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise

    logger.info(f"Skeletonization completed for mesh {em_cell_mesh_id}")

    return SkeletonizationJobOutput(
        reconstruction_morphology=morphology,
    )
