from typing import List
from uuid import UUID

from entitysdk.common import ProjectContext

from app.domains.circuit.circuit import CircuitOrigin
from app.services.worker.circuit.simulation import (
    get_batch_circuit_simulation_params_map,
    get_circuit_simulation_params,
    run_circuit_simulation,
)


def run(
    simulation_id: UUID,
    circuit_origin: CircuitOrigin,
    *,
    access_token: str,
    circuit_id: UUID,
    execution_id: UUID,
    project_context: ProjectContext,
) -> None:
    run_circuit_simulation(
        simulation_id,
        circuit_origin=circuit_origin,
        access_token=access_token,
        circuit_id=circuit_id,
        execution_id=execution_id,
        project_context=project_context,
    )


def get_params(
    simulation_id: UUID,
    circuit_origin: CircuitOrigin,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    get_circuit_simulation_params(
        simulation_id,
        circuit_origin=circuit_origin,
        access_token=access_token,
        project_context=project_context,
    )


def get_batch_params_map(
    simulation_ids: List[UUID],
    circuit_origin: CircuitOrigin,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    get_batch_circuit_simulation_params_map(
        simulation_ids,
        circuit_origin=circuit_origin,
        access_token=access_token,
        project_context=project_context,
    )
