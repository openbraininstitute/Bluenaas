from uuid import UUID

from entitysdk.common import ProjectContext

from app.services.worker.ion_channel.build import run_ion_channel_build


def run(
    config_id: UUID,
    *,
    execution_id: UUID,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_ion_channel_build(
        config_id,
        execution_id=execution_id,
        access_token=access_token,
        project_context=project_context,
    )
