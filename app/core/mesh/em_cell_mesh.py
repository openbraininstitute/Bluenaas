from pathlib import Path
from uuid import UUID

from entitysdk import Client
from entitysdk._server_schemas import AssetLabel
from entitysdk.models import EMCellMesh as EntitycoreEMCellMesh
from entitysdk.models.asset import Asset
from filelock import FileLock
from loguru import logger

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.exceptions import EMCellMeshInitError
from app.infrastructure.storage import get_mesh_location, rm_dir


class EMCellMesh:
    mesh_id: UUID
    initialized: bool = False
    metadata: EntitycoreEMCellMesh
    path: Path

    def __init__(self, em_cell_mesh_id: UUID, client: Client) -> None:
        self.mesh_id = em_cell_mesh_id
        self.path = get_mesh_location(self.mesh_id)

        self.client = client

        self._fetch_metadata()

    def _fetch_metadata(self):
        """Fetch the EMCellMesh metadata from entitycore"""
        self.metadata = self.client.get_entity(self.mesh_id, entity_type=EntitycoreEMCellMesh)

    @property
    def mesh_asset(self) -> Asset:
        if not self.initialized:
            self.init()

        mesh_asset = next(
            (
                asset
                for asset in self.metadata.assets
                if asset.label == AssetLabel.cell_surface_mesh
            ),
            None,
        )

        if not mesh_asset:
            raise EMCellMeshInitError("No mesh asset found")

        return mesh_asset

    def _fetch_assets(self):
        """Fetch the mesh file from entitycore and write to the disk storage"""
        assert self.metadata.id is not None

        logger.debug(f"Fetching EMCellMesh {self.mesh_id}")

        self.client.download_assets(
            self.metadata,
            selection={"label": AssetLabel.cell_surface_mesh},
            output_path=self.path,
        ).one()

        logger.debug(f"EMCellMesh {self.mesh_id} fetched")

    @property
    def file_path(self) -> Path:
        # Take first file in the path
        return self.path / self.mesh_asset.path

    def init(self) -> None:
        """Fetch mesh assets and compile MOD files"""
        if self.initialized:
            logger.debug("EMCellMesh already initialized")
            return

        ready_marker = self.path / READY_MARKER_FILE_NAME

        if ready_marker.exists():
            logger.debug("Found existing EMCellMesh in the storage")
            self.initialized = True
            return

        lock = FileLock(self.path / DIR_LOCK_FILE_NAME)

        try:
            logger.debug("Acquiring lock for EMCellMesh initialization")
            with lock.acquire(timeout=2 * 60):
                logger.debug("Lock acquired for EMCellMesh initialization")
                # Re-check if the circuit is already initialized.
                # Another worker might have initialized the circuit
                # while the current one was waiting for the lock.
                if ready_marker.exists():
                    logger.debug("Found existing EMCellMesh in the storage")
                    self.initialized = True
                    return

                self._fetch_assets()
                ready_marker.touch()
        except Exception:
            raise EMCellMeshInitError()

    def cleanup(self) -> None:
        """Cleanup the mesh"""
        rm_dir(self.path)
        self.initialized = False
