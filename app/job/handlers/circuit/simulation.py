from datetime import UTC, datetime
import json
from uuid import UUID

from entitysdk.client import Client
from entitysdk.common import ProjectContext
from loguru import logger

from app.config.settings import settings
from app.core.circuit.circuit import Circuit
from app.core.circuit.simulation import Simulation
from app.infrastructure.redis import close_stream, stream
from app.infrastructure.rq import get_current_stream_key
from entitysdk.models import SimulationExecution


def run_circuit_simulation(
    *,
    circuit_id: str,
    simulation_id: str,
    execution_id: str,
    access_token: str,
    project_context: ProjectContext,
):
    stream_key = get_current_stream_key()

    num_cores = 4

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    client.update_entity(
        entity_id=UUID(execution_id),
        entity_type=SimulationExecution,
        attrs_or_entity={
            "status": "running",
        },
    )

    circuit = Circuit(circuit_id=circuit_id, client=client)

    logger.info(f"Initializing circuit {circuit_id}")
    stream(stream_key, json.dumps({"status": "initializing circuit"}))
    circuit.init()

    simulation = Simulation(
        circuit_id=circuit_id,
        simulation_id=simulation_id,
        client=client,
        execution_id=execution_id,
    )

    stream(stream_key, json.dumps({"status": "initializing simulation"}))
    simulation.init()

    stream(stream_key, json.dumps({"status": "running simulation"}))

    simulation_output = simulation.run()
    simulation_result_entity = simulation_output.upload()

    client.update_entity(
        entity_id=UUID(execution_id),
        entity_type=SimulationExecution,
        attrs_or_entity={
            "generated_ids": [simulation_result_entity.id],
            "end_time": datetime.now(UTC),
            "status": "done",
        },
    )

    stream(stream_key, json.dumps({"status": "done"}))

    close_stream(stream_key)
