from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from entitysdk import Client
from entitysdk.models import IonChannelModelingCampaign
from obi_one import GridScanGenerationTask, run_task_for_single_configs
from obi_one.scientific.tasks.ion_channel_modeling import IonChannelFittingScanConfig

from app.core.exceptions import IonChannelBuildError, NotInitializedError
from app.infrastructure.storage import get_ion_channel_build_location, rm_dir


class Build:
    raw_config: dict
    config: IonChannelFittingScanConfig | None
    grid_scan: GridScanGenerationTask | None
    path: Path
    client: Client

    def __init__(self, config: dict, *, client: Client, execution_id: UUID | None = None):
        self.raw_config = config
        self.client = client

        self.path = get_ion_channel_build_location(execution_id or uuid4())

    def init(self) -> IonChannelModelingCampaign:
        self.config = IonChannelFittingScanConfig.model_validate(self.raw_config)

        self.grid_scan = GridScanGenerationTask(
            form=self.config, coordinate_directory_option="ZERO_INDEX", output_root=self.path
        )
        self.grid_scan.multiple_value_parameters(display=True)
        self.grid_scan.coordinate_parameters(display=True)

        campaign = self.grid_scan.execute(db_client=self.client)

        return cast(IonChannelModelingCampaign, campaign)

    def run(self):
        if not self.config or not self.grid_scan:
            raise NotInitializedError("Build not initialized")

        try:
            ion_channel_models = run_task_for_single_configs(
                single_configs=self.grid_scan.single_configs, db_client=self.client
            )
        except Exception as e:
            raise IonChannelBuildError() from e

        return ion_channel_models

    def cleanup(self) -> None:
        """Cleanup"""
        rm_dir(self.path)
