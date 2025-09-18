from uuid import UUID, uuid4

from entitysdk import Client
from loguru import logger

from app.core.mesh.em_cell_mesh import EMCellMesh
from app.core.mesh.skeletonization_output import SkeletonizationOutput
from app.domains.mesh.skeletonization import SkeletonizationParams
from app.utils.safe_process import SafeProcessExecutor


class Skeletonization:
    mesh: EMCellMesh
    output: SkeletonizationOutput
    initialized: bool = False
    execution_id: UUID
    params: SkeletonizationParams

    def __init__(
        self,
        em_cell_mesh_id: UUID,
        params: SkeletonizationParams,
        *,
        client: Client,
        execution_id: UUID | None = None,
    ):
        self.em_cell_mesh_id = em_cell_mesh_id
        self.params = params
        self.execution_id = execution_id or uuid4()

        self.mesh = EMCellMesh(em_cell_mesh_id, client)
        self.output = SkeletonizationOutput(self.execution_id, client)

    def init(self):
        self.mesh.init()
        self.output.init()

    def run(self):
        import ultraliser  # pyright: ignore[reportMissingImports]

        params_dict = {k: v for k, v in self.params.model_dump().items() if v is not None}

        logger.info(f"Running skeletonization for mesh {self.mesh.mesh_id}")
        logger.info(f"Parameters: {params_dict}")

        executor = SafeProcessExecutor()

        result = executor.execute(
            ultraliser.skeletonizeNeuronMesh,
            mesh=str(self.mesh.file_path),
            output_directory=str(self.output.path),
            **params_dict,
        )

        logger.info(f"Process logs:\n{result.logs}")
