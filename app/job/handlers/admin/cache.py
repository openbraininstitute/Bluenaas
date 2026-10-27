from app.infrastructure.storage.epoch import CacheKind
from app.services.worker.admin.cache import reclaim_retired_cache


def reclaim(
    kind: str,
    attempt: int,
    previous_epoch: str | None = None,
    follow_up: bool = True,
    mark: bool = True,
) -> dict:
    return reclaim_retired_cache(CacheKind(kind), attempt, previous_epoch, follow_up, mark)
