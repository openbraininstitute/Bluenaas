from uuid import UUID

from entitysdk import Client

from app.core.mesh.em_cell_mesh import EMCellMesh
from app.domains.mesh.analysis import AnalysisResult
from app.utils.safe_process import SafeProcessExecutor


class Analysis:
    execution_id: UUID
    initialized: bool = False
    mesh: EMCellMesh

    def __init__(
        self,
        em_cell_mesh_id: UUID,
        *,
        client: Client,
    ):
        self.em_cell_mesh_id = em_cell_mesh_id
        self.mesh = EMCellMesh(em_cell_mesh_id, client)

    def init(self):
        self.mesh.init()
        self.initialized = True

    def run(self):
        if not self.initialized:
            raise RuntimeError("Analysis not initialized")

        import ultraliser  # pyright: ignore[reportMissingImports]

        executor = SafeProcessExecutor()

        execution = executor.execute(
            ultraliser.estimate_mesh_scanning_volume_nm3_um3,
            mesh_path=str(self.mesh.file_path),
        )

        return AnalysisResult(approximate_volume=int(execution.result))
