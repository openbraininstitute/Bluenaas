from http import HTTPStatus

from fastapi import APIRouter, Depends
from rq import Queue

from app.infrastructure.kc.auth import AdminAuthDep
from app.infrastructure.rq import JobQueue, queue_factory
from app.infrastructure.storage.epoch import CacheKind
from app.services.api.admin.cache import start_cache_cleanup

router = APIRouter(prefix="/admin")


@router.delete("/cache/circuit", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_circuit_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await start_cache_cleanup(
        CacheKind.CIRCUIT, job_queue=job_queue, description="Circuit cache"
    )


@router.delete("/cache/single-neuron", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_single_neuron_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await start_cache_cleanup(
        CacheKind.SINGLE_NEURON, job_queue=job_queue, description="Single neuron cache"
    )


@router.delete("/cache/mesh", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_mesh_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await start_cache_cleanup(CacheKind.MESH, job_queue=job_queue, description="Mesh cache")


@router.delete("/cache/task-config", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_task_config_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await start_cache_cleanup(
        CacheKind.TASK_CONFIG, job_queue=job_queue, description="Task config cache"
    )


@router.delete("/cache/compilation", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_compilation_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await start_cache_cleanup(
        CacheKind.COMPILATION, job_queue=job_queue, description="Compilation cache"
    )
