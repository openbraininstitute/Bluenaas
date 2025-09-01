from pathlib import Path
from uuid import UUID

from app.infrastructure.storage import ensure_dir, get_mesh_skeletonization_output_location, rm_dir


class SkeletonizationOutput:
    output_id: UUID
    path: Path

    def __init__(self, output_id: UUID) -> None:
        self.output_id = output_id
        self.path = get_mesh_skeletonization_output_location(self.output_id)

    def list_files(self) -> list[Path]:
        return [p for p in self.path.rglob("*") if p.is_file()]

    def init(self) -> None:
        ensure_dir(self.path)

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        rm_dir(self.path)
