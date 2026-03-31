from uuid import UUID

from entitysdk import ProjectContext

from app.services.worker.single_neuron.compatibility import run_compatibility_check


def check(
    morphology_id: UUID,
    emodel_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_compatibility_check(
        morphology_id,
        emodel_id,
        access_token=access_token,
        project_context=project_context,
    )
