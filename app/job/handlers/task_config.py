from uuid import UUID

from entitysdk.common import ProjectContext
from obi_one.types import TaskType

from app.infrastructure.storage import get_task_config_run_location
from app.services.worker.task_config import run_task_config


def run(
    task_type: str,
    config_id: UUID,
    *,
    execution_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_task_config(
        TaskType(task_type),
        config_id,
        output_root=get_task_config_run_location(execution_id),
        execution_id=execution_id,
        access_token=access_token,
        project_context=project_context,
    )
