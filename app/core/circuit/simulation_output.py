from pathlib import Path
from uuid import UUID

from entitysdk.client import Client
from entitysdk.models import SimulationResult
from entitysdk.models.core import Identifiable
from entitysdk.types import AssetLabel, ContentType
from loguru import logger

from app.infrastructure.storage import get_circuit_simulation_output_location, rm_dir


class SimulationOutput:
    simulation_id: UUID
    execution_id: UUID
    output_path: Path
    client: Client

    def __init__(self, simulation_id: UUID, execution_id: UUID, client: Client):
        self.simulation_id = simulation_id
        self.execution_id = execution_id
        self.client = client

        self.output_path = get_circuit_simulation_output_location(execution_id)

    def _upload_file(
        self,
        *,
        path: Path,
        content_type: ContentType,
        asset_label: AssetLabel,
        entity_id: UUID,
        client: Client,
        raise_on_missing=True,
    ) -> None:
        """Upload a single file if it exists"""
        if not path.exists():
            msg = f"{path.name} can not be found"

            if raise_on_missing:
                raise FileNotFoundError(msg)
            else:
                logger.warning(msg)
                return

        with open(path, "rb") as f:
            client.upload_content(
                entity_id=entity_id,
                entity_type=SimulationResult,
                file_name=path.name,
                file_content=f,
                file_content_type=content_type,
                asset_label=asset_label,
            )

    def upload(self) -> Identifiable:
        """Upload simulation artefacts to entitycore"""

        # TODO: Add proper name, consider adding a description
        simulation_result = self.client.register_entity(
            SimulationResult(
                name="simulation_result",
                description="Simulation result",
                simulation_id=self.simulation_id,
            )
        )
        assert simulation_result.id
        logger.info(f"Registered simulation result {simulation_result.id}")

        # Upload spike report
        spike_report_path = self.output_path / "spikes.h5"
        self._upload_file(
            client=self.client,
            path=spike_report_path,
            content_type=ContentType.application_x_hdf5,
            asset_label=AssetLabel.spike_report,
            entity_id=simulation_result.id,
            raise_on_missing=False,
        )

        # Upload NWB voltage report
        self._upload_file(
            client=self.client,
            path=self.output_path / "voltage_report.nwb",
            content_type=ContentType.application_nwb,
            asset_label=AssetLabel.voltage_report,
            entity_id=simulation_result.id,
            raise_on_missing=False,
        )

        # Upload the rest of HDF5 files, witch are mostly voltage reports
        for h5_file in self.output_path.glob("*.h5"):
            if h5_file.name == "spikes.h5":
                continue

            self._upload_file(
                client=self.client,
                path=h5_file,
                content_type=ContentType.application_x_hdf5,
                asset_label=AssetLabel.voltage_report,
                entity_id=simulation_result.id,
            )

        return simulation_result

    def cleanup(self):
        """Cleanup the simulation output"""
        # TODO: Make instance re-initializable
        rm_dir(self.output_path)
