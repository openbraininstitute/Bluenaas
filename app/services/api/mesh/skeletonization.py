from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.models import EMCellMesh, SkeletonizationExecution
from entitysdk.types import SkeletonizationExecutionStatus
from fastapi import HTTPException
from rq import Queue

from app.config.settings import settings
from app.core.job import JobInfo
from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationUltraliserParams,
)
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.rq_job import dispatch, get_job_info, run_async


async def run_mesh_skeletonization(
    em_cell_mesh_id: UUID,
    input_params: SkeletonizationInputParams,
    ultraliser_params: SkeletonizationUltraliserParams,
    *,
    auth: Auth,
    job_queue: Queue,
    project_context: ProjectContext,
) -> JobInfo:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    em_cell_mesh = await run_async(
        lambda: client.get_entity(
            em_cell_mesh_id,
            entity_type=EMCellMesh,
        )
    )

    execution_entity = await run_async(
        lambda: client.register_entity(
            SkeletonizationExecution(
                used=[em_cell_mesh],
                start_time=datetime.now(UTC),
                status=SkeletonizationExecutionStatus.created,
            )
        )
    )

    execution_id = execution_entity.id
    assert execution_id

    async def on_failure(exc_type: type[BaseException] | None) -> None:
        try:
            await run_async(
                lambda: client.update_entity(
                    entity_id=execution_id,
                    entity_type=SkeletonizationExecution,
                    attrs_or_entity={
                        "end_time": datetime.now(UTC),
                        "status": SkeletonizationExecutionStatus.error,
                    },
                )
            )
        except Exception:
            # TODO ignore only specific exception entitysdk raises when an entity is not found.
            pass

    job, _stream = await dispatch(
        job_queue,
        JobFn.RUN_MESH_SKELETONIZATION,
        timeout=60 * 60 * 3,  # 3 hours
        result_ttl=60 * 60 * 24 * 30,  # 30 days
        job_args=(em_cell_mesh_id, input_params, ultraliser_params),
        job_kwargs={
            "auth": auth,
            "project_context": project_context,
            "execution_id": execution_id,
        },
        on_failure=on_failure,
    )

    return await get_job_info(job)


async def get_mesh_skeletonization_status(job_id: UUID, *, job_queue: Queue) -> JobInfo:
    job = await run_async(lambda: job_queue.fetch_job(str(job_id)))

    if job is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"message": "Job not found", "job_id": str(job_id)},
        )

    return await get_job_info(job)
