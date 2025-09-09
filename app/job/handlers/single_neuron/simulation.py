from http import HTTPStatus as status
from uuid import UUID

from loguru import logger

from app.core.exceptions import AppError, AppErrorCode
from app.domains.simulation import SingleNeuronSimulationConfig
from app.external.entitycore.service import ProjectContext
from app.services.worker.single_neuron.simulation import run_simulation


def run(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    realtime: bool,
    access_token: str,
    project_context: ProjectContext,
):
    """Simulation runner"""
    try:
        run_simulation(
            model_id=model_id,
            config=config,
            realtime=realtime,
            access_token=access_token,
            project_context=project_context,
        )
    except Exception as ex:
        logger.exception(f"Running simulation failed {ex}")
        raise AppError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=AppErrorCode.INTERNAL_SERVER_ERROR,
            message="Running simulation failed",
            details=str(ex),
        ) from ex
