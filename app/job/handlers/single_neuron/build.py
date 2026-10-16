from uuid import UUID

from entitysdk.common import ProjectContext
from obi_one.types import TaskType

from app.infrastructure.storage import get_single_neuron_build_location
from app.services.worker.task_config import run_task_config


def run(
    config_id: UUID,
    *,
    execution_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_task_config(
        TaskType.memodel_build,
        config_id,
        output_root=get_single_neuron_build_location(execution_id),
        execution_id=execution_id,
        access_token=access_token,
        project_context=project_context,
    )
