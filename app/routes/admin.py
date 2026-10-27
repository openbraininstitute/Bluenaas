from enum import StrEnum
from http import HTTPStatus

from fastapi import APIRouter

from app.infrastructure.kc.auth import AdminAuthDep
from app.infrastructure.storage.epoch import CacheKind
from app.services.api.admin.cache import start_cache_cleanup

router = APIRouter(prefix="/admin")


class Cache(StrEnum):
    CIRCUIT = "circuit"
    SINGLE_NEURON = "single-neuron"
    MESH = "mesh"
    TASK_CONFIG = "task-config"
    COMPILATION = "compilation"


_CACHES: dict[Cache, tuple[CacheKind, str]] = {
    Cache.CIRCUIT: (CacheKind.CIRCUIT, "Circuit cache"),
    Cache.SINGLE_NEURON: (CacheKind.SINGLE_NEURON, "Single neuron cache"),
    Cache.MESH: (CacheKind.MESH, "Mesh cache"),
    Cache.TASK_CONFIG: (CacheKind.TASK_CONFIG, "Task config cache"),
    Cache.COMPILATION: (CacheKind.COMPILATION, "Compilation cache"),
}


@router.delete("/cache/{cache}", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_cache(cache: Cache, _: AdminAuthDep):
    kind, description = _CACHES[cache]
    return await start_cache_cleanup(kind, description=description)
