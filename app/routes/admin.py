from http import HTTPStatus

from fastapi import APIRouter, Depends
from rq import Queue

from app.constants import CACHE_CLEANUP_TIMEOUT
from app.context import cid_var
from app.infrastructure.kc.auth import AdminAuthDep
from app.infrastructure.rq import JobQueue, queue_factory
from app.infrastructure.storage.epoch import CacheKind
from app.job import JobFn
from app.utils.asyncio import run_async

router = APIRouter(prefix="/admin")


async def _start_cache_cleanup(kind: CacheKind, job_queue: Queue, description: str) -> dict:
    job = await run_async(
        lambda: job_queue.enqueue(
            JobFn.CLEAR_CACHE,
            kind.value,
            job_timeout=CACHE_CLEANUP_TIMEOUT,
            meta={"cid": cid_var.get()},
        )
    )
    return {"message": f"{description} cleanup started", "job_id": job.id}


@router.delete("/cache/circuit", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_circuit_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await _start_cache_cleanup(CacheKind.CIRCUIT, job_queue, "Circuit cache")


@router.delete("/cache/single-neuron", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_single_neuron_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await _start_cache_cleanup(CacheKind.SINGLE_NEURON, job_queue, "Single neuron cache")


@router.delete("/cache/mesh", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_mesh_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await _start_cache_cleanup(CacheKind.MESH, job_queue, "Mesh cache")


@router.delete("/cache/ion-channel", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_ion_channel_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await _start_cache_cleanup(CacheKind.ION_CHANNEL, job_queue, "Ion channel cache")


@router.delete("/cache/compilation", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_compilation_storage(
    _: AdminAuthDep, job_queue: Queue = Depends(queue_factory(JobQueue.MEDIUM))
):
    return await _start_cache_cleanup(CacheKind.COMPILATION, job_queue, "Compilation cache")
