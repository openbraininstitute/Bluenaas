from uuid import UUID

from entitysdk.common import ProjectContext

from app.services.worker.circuit.simulation import (
    get_circuit_simulation_params,
    run_circuit_simulation,
)


def run(
    simulation_id: UUID,
    *,
    access_token: str,
    circuit_id: UUID,
    execution_id: UUID,
    project_context: ProjectContext,
) -> None:
    run_circuit_simulation(
        simulation_id,
        access_token=access_token,
        circuit_id=circuit_id,
        execution_id=execution_id,
        project_context=project_context,
    )


def get_params(
    simulation_id: UUID,
    *,
    access_token: str,
    circuit_id: UUID,
    project_context: ProjectContext,
) -> None:
    get_circuit_simulation_params(
        simulation_id,
        access_token=access_token,
        circuit_id=circuit_id,
        project_context=project_context,
    )
