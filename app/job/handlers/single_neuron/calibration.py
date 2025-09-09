from uuid import UUID

from entitysdk import ProjectContext

from app.services.worker.single_neuron.calibration import run_single_neuron_calibration


def run(
    model_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_single_neuron_calibration(
        model_id,
        access_token=access_token,
        project_context=project_context,
    )
