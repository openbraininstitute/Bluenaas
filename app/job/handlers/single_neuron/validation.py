from uuid import UUID

from entitysdk import ProjectContext

from app.services.worker.single_neuron.validation import run_single_neuron_validation


def run(
    model_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_single_neuron_validation(
        model_id,
        access_token=access_token,
        project_context=project_context,
    )
