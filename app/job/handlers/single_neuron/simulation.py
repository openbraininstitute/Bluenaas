from http import HTTPStatus as status
from uuid import UUID

from loguru import logger

from app.core.exceptions import AppError, AppErrorCode
from app.domains.simulation import SingleNeuronSimulationConfig
from app.external.entitycore.service import ProjectContext
from app.services.worker.single_neuron.unified_simulation import run_unified_simulation


def run(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    realtime: bool,
    access_token: str,
    project_context: ProjectContext,
):
    """Unified simulation runner that handles both current and frequency varying simulations."""
    try:
        run_unified_simulation(
            model_id=model_id,
            config=config,
            realtime=realtime,
            access_token=access_token,
            project_context=project_context,
        )
    except Exception as ex:
        logger.exception(f"running simulation failed {ex}")
        raise AppError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=AppErrorCode.INTERNAL_SERVER_ERROR,
            message="running simulation failed",
            details=str(ex),
        ) from ex
