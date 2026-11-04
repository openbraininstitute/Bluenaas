from uuid import UUID

from app.infrastructure.rq import JobQueue, get_current_job_id
from app.services.worker.simulation_result.lfp_summary import build_lfp_summary


def build(*, asset_id: UUID, epoch: str, queue: str, url: str, size: int) -> None:
    build_lfp_summary(
        asset_id,
        epoch=epoch,
        queue=JobQueue(queue),
        job_id=get_current_job_id(),
        url=url,
        size=size,
    )
