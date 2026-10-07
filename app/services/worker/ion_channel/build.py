from datetime import UTC, datetime
from uuid import UUID

from entitysdk import Client, ProjectContext
from entitysdk.models import TaskActivity, TaskConfig
from entitysdk.types import ActivityStatus
from obi_one.core.run_tasks import run_task_type
from obi_one.types import TaskType

from app.config.settings import settings
from app.infrastructure.storage import get_ion_channel_build_location, rm_dir
from app.logging import worker_subprocess


@worker_subprocess
def run_ion_channel_build(
    config_id: UUID,
    *,
    execution_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    def set_status(status: ActivityStatus, **attrs) -> None:
        client.update_entity(
            entity_id=execution_id,
            entity_type=TaskActivity,
            attrs_or_entity={"status": status, **attrs},
        )

    output_root = get_ion_channel_build_location(execution_id)
    set_status(ActivityStatus.running)

    try:
        run_task_type(
            task_type=TaskType.ion_channel_fitting,
            entity_type=TaskConfig,
            entity_id=str(config_id),
            scan_output_root=str(output_root),
            db_client=client,
            execution_activity_id=str(execution_id),
        )
    except Exception:
        set_status(ActivityStatus.error, end_time=datetime.now(UTC))
        raise
    finally:
        rm_dir(output_root)

    set_status(ActivityStatus.done, end_time=datetime.now(UTC))
