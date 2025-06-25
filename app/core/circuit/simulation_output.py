from pathlib import Path

from entitysdk.client import Client

from app.infrastructure.storage import get_circuit_simulation_location


class SimulationOutput:
    execution_id: str
    output_path: Path
    client: Client

    def __init__(self, execution_id: str, client: Client):
        self.execution_id = execution_id
        self.client = client

        self.output_path = get_circuit_simulation_location(execution_id)

    def upload(self):
        """Upload simulation artefacts to entitycore"""
        pass
