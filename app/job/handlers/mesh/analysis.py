from uuid import UUID

from entitysdk import ProjectContext

from app.services.worker.mesh.analysis import run_mesh_analysis


def run(
    simulation_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    run_mesh_analysis(
        simulation_id,
        access_token=access_token,
        project_context=project_context,
    )
