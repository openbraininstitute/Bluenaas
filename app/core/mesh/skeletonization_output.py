from pathlib import Path
from uuid import UUID
from loguru import logger

from entitysdk.client import Client
from entitysdk.models import ReconstructionMorphology

from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir


class SkeletonizationOutput:
    output_id: UUID
    path: Path
    client: Client

    def __init__(self, output_id: UUID, client: Client) -> None:
        self.output_id = output_id
        self.client = client
        self.path = get_mesh_skeletonization_output_location(self.output_id)

    # def list_files(self) -> list[str]:
    #     return [str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file()]

    def init(self) -> None:
        ensure_dir(self.path)

    def upload(self):
        logger.info(f"Uploading skeletonization output for {self.output_id}")
        pass

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        rm_dir(self.path)
