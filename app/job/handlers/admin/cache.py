from app.infrastructure.storage.epoch import CacheKind
from app.services.worker.admin.cache import clear_cache, reclaim_retired_cache


def clear(kind: str) -> dict:
    return clear_cache(CacheKind(kind))


def reclaim(kind: str, attempt: int) -> dict:
    return reclaim_retired_cache(CacheKind(kind), attempt)
