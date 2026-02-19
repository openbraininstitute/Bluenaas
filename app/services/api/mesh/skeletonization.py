import json
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.models import EMCellMesh, SkeletonizationConfig, SkeletonizationExecution
from entitysdk.types import ActivityStatus
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.config.settings import settings
from app.core.http_stream import x_ndjson_http_stream
from app.core.job import JobInfo
from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationUltraliserParams,
)
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.asyncio import interleave_async_iterators
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
                status=ActivityStatus.created,
            )
        )
    )

    execution_id = execution_entity.id
    assert execution_id

    async def on_failure(exc_type: type[BaseException] | None = None) -> None:
        try:
            await run_async(
                lambda: client.update_entity(
                    entity_id=execution_id,
                    entity_type=SkeletonizationExecution,
                    attrs_or_entity={
                        "end_time": datetime.now(UTC),
                        "status": ActivityStatus.error,
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


async def run_mesh_skeletonization_batch(
    skeletonization_config_ids: list[UUID],
    *,
    auth: Auth,
    job_queue: Queue,
    request: Request,
    project_context: ProjectContext,
    stream: bool = False,
) -> list[JobInfo] | StreamingResponse:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    job_infos = []
    job_streams = []

    for config_id in skeletonization_config_ids:
        # Fetch config
        config = await run_async(
            lambda: client.get_entity(config_id, entity_type=SkeletonizationConfig)
        )

        # Get em_cell_mesh_id from config
        em_cell_mesh_id = config.em_cell_mesh_id

        # Fetch mesh to get name
        em_cell_mesh = await run_async(
            lambda: client.get_entity(em_cell_mesh_id, entity_type=EMCellMesh)
        )

        # Create input params with mesh name and default description
        input_params = SkeletonizationInputParams(
            name=em_cell_mesh.name or f"Morphology {em_cell_mesh_id}",
            description="Reconstructed morphology from an EM surface mesh",
        )

        # Download and parse config
        content = await run_async(
            lambda: client.download_content(
                entity_id=config_id,
                entity_type=SkeletonizationConfig,
                asset_id=config.assets[0].id,
            )
        )
        config_json = json.loads(content)

        # Extract ultraliser params from initialize block
        ultraliser_params = SkeletonizationUltraliserParams(**config_json["initialize"])

        # Create execution entity with config in used array
        execution_entity = await run_async(
            lambda: client.register_entity(
                SkeletonizationExecution(
                    used=[config],
                    start_time=datetime.now(UTC),
                    status=ActivityStatus.created,
                )
            )
        )

        exec_id = execution_entity.id
        assert exec_id

        async def on_failure(
            _exc_type: type[BaseException] | None = None, execution_id=exec_id
        ) -> None:
            try:
                await run_async(
                    lambda: client.update_entity(
                        entity_id=execution_id,
                        entity_type=SkeletonizationExecution,
                        attrs_or_entity={
                            "end_time": datetime.now(UTC),
                            "status": ActivityStatus.error,
                        },
                    )
                )
            except Exception:
                pass

        # Dispatch job
        job, job_stream = await dispatch(
            job_queue,
            JobFn.RUN_MESH_SKELETONIZATION,
            timeout=60 * 60 * 3,  # 3 hours
            result_ttl=60 * 60 * 1,  # 1 hour
            job_args=(em_cell_mesh_id, input_params, ultraliser_params),
            job_kwargs={
                "auth": auth,
                "project_context": project_context,
                "execution_id": exec_id,
            },
            on_failure=on_failure,
        )

        job_infos.append(await get_job_info(job))
        job_streams.append(job_stream)

    if stream is True:
        job_stream = interleave_async_iterators(job_streams)
        http_stream = x_ndjson_http_stream(request, job_stream)
        return StreamingResponse(http_stream, media_type="application/x-ndjson")
    else:
        return job_infos
