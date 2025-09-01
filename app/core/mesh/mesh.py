from pathlib import Path
from uuid import UUID

from app.infrastructure.storage import ensure_dir, get_mesh_location, rm_dir


class Mesh:
    file_path: Path | None = None
    initialized: bool = False
    mesh_id: UUID
    path: Path

    def __init__(self, mesh_id: UUID) -> None:
        self.mesh_id = mesh_id
        self.path = get_mesh_location(self.mesh_id)

    def init(self) -> None:
        ensure_dir(self.path)
        self.file_path = next(self.path.iterdir())
        self.initialized = True

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        rm_dir(self.path)
        self.initialized = False
        self.file_path = None
