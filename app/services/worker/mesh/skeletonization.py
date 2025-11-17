from uuid import UUID

from entitysdk import Client, ProjectContext
from httpx import Client as HttpxClient
from httpx import Timeout
from loguru import logger

from app.config.settings import settings
from app.core.mesh.skeletonization import Skeletonization
from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationJobOutput,
    SkeletonizationUltraliserParams,
)
from app.utils.safe_process import SafeProcessRuntimeError


def run_mesh_skeletonization(
    em_cell_mesh_id: UUID,
    input_params: SkeletonizationInputParams,
    ultraliser_params: SkeletonizationUltraliserParams,
    *,
    execution_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> SkeletonizationJobOutput:
    httpx_client = HttpxClient(timeout=Timeout(10, read=20))

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
        http_client=httpx_client,
    )

    skeletonization = Skeletonization(
        em_cell_mesh_id,
        input_params,
        ultraliser_params,
        client=client,
        execution_id=execution_id,
    )

    try:
        skeletonization.init()
        skeletonization.run()
        skeletonization.output.post_process()
        morphology = skeletonization.output.upload()
    except SafeProcessRuntimeError as e:
        logger.error(f"Skeletonization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
    finally:
        skeletonization.output.cleanup()
        httpx_client.close()

    logger.info(f"Skeletonization completed for mesh {em_cell_mesh_id}")

    return SkeletonizationJobOutput(
        morphology=morphology,
    )
