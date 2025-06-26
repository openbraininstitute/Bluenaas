from pathlib import Path
from uuid import UUID

from entitysdk.client import Client
from entitysdk.models import SimulationResult
from entitysdk.models.core import Identifiable
from loguru import logger

from app.infrastructure.storage import get_circuit_simulation_output_location


class SimulationOutput:
    simulation_id: str
    execution_id: str
    output_path: Path
    client: Client

    def __init__(self, simulation_id: str, execution_id: str, client: Client):
        self.simulation_id = simulation_id
        self.execution_id = execution_id
        self.client = client

        self.output_path = get_circuit_simulation_output_location(execution_id)

    def upload(self) -> Identifiable:
        """Upload simulation artefacts to entitycore"""

        # TODO: Add proper name, consider adding a description
        simulation_result = self.client.register_entity(
            SimulationResult(
                name="simulation_result",
                description="Simulation result",
                simulation_id=UUID(self.simulation_id),
            )
        )
        assert simulation_result.id

        for file_path in self.output_path.rglob("*"):
            # TODO: Futher filter out files that do not have to be uploaded
            if file_path.is_file():
                logger.info(f"Uploading {file_path}")
                with open(file_path, "rb") as f:
                    self.client.upload_content(
                        entity_id=simulation_result.id,
                        entity_type=SimulationResult,
                        file_name=file_path.name,
                        file_content=f,
                        file_content_type="tbd",
                    )

        return simulation_result
