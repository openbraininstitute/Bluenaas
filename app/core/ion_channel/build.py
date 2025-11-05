from pathlib import Path
from uuid import UUID, uuid4

from entitysdk import Client
from obi_one import GridScanGenerationTask, run_task_for_single_configs
from obi_one.scientific.tasks.ion_channel_modeling import IonChannelFittingScanConfig

from app.core.exceptions import IonChannelBuildError, NotInitializedError
from app.infrastructure.storage import get_ion_channel_build_location, rm_dir


class Build:
    raw_config: dict
    config: IonChannelFittingScanConfig | None
    path: Path
    client: Client

    def __init__(self, config: dict, *, client: Client, execution_id: UUID | None = None):
        self.raw_config = config
        self.client = client

        self.path = get_ion_channel_build_location(execution_id or uuid4())

    def init(self):
        self.config = IonChannelFittingScanConfig.model_validate(self.raw_config)

    def run(self):
        if not self.config:
            raise NotInitializedError("Build not initialized")

        try:
            grid_scan = GridScanGenerationTask(form=self.config, output_root=self.path)
            grid_scan.execute(db_client=self.client)
            run_task_for_single_configs(
                single_configs=grid_scan.single_configs, db_client=self.client
            )
        except Exception as e:
            raise IonChannelBuildError() from e

    def cleanup(self) -> None:
        """Cleanup"""
        rm_dir(self.path)
