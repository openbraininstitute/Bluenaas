from uuid import UUID

from entitysdk import Client
from loguru import logger

from app.core.mesh.em_cell_mesh import EMCellMesh
from app.utils.safe_process import SafeProcessExecutor
from app.domains.mesh.analysis import AnalysisResult


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

        logger.info(f"Running analysis for mesh {self.mesh.mesh_id}")

        executor = SafeProcessExecutor()

        result = executor.execute(
            ultraliser.evaluate_neuron_skeletonization_pricing_params,
            mesh=str(self.mesh.file_path),
        )

        return AnalysisResult(**result.result)
