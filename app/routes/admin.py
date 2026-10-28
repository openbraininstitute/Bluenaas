from http import HTTPStatus

from fastapi import APIRouter

from app.infrastructure.kc.auth import AdminAuthDep
from app.infrastructure.storage.epoch import CacheKind
from app.services.api.admin.cache import start_cache_cleanup

router = APIRouter(prefix="/admin")


@router.delete("/cache/{cache}", tags=["admin"], status_code=HTTPStatus.ACCEPTED)
async def clear_cache(cache: CacheKind, _: AdminAuthDep):
    return await start_cache_cleanup(cache)
