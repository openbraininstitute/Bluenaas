from entitysdk.common import ProjectContext

from app.services.worker.ion_channel.build import run_ion_channel_build


def run(
    config: dict,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_ion_channel_build(
        config,
        access_token=access_token,
        project_context=project_context,
    )
