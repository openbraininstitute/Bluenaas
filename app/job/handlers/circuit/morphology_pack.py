from uuid import UUID

from entitysdk.common import ProjectContext

from app.infrastructure.rq import JobQueue, get_current_job_id
from app.services.worker.circuit.morphology_pack import build_circuit_morphology_pack


def build(
    *,
    circuit_id: UUID,
    epoch: str,
    queue: str,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    build_circuit_morphology_pack(
        circuit_id,
        epoch=epoch,
        queue=JobQueue(queue),
        job_id=get_current_job_id(),
        access_token=access_token,
        project_context=project_context,
    )
