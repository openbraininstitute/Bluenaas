import multiprocessing as mp
from http import HTTPStatus as status
from uuid import UUID

from loguru import logger

from app.core.exceptions import BlueNaasError, BlueNaasErrorCode
from app.domains.simulation import SingleNeuronSimulationConfig
from app.external.entitycore.service import ProjectContext
from app.services.worker.single_cell.simulation import (
    init_current_varying_simulation,
    init_frequency_varying_simulation,
    is_current_varying_simulation,
    stream_realtime_data,
)


def run(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    realtime: bool,
    access_token: str,
    project_context: ProjectContext,
):
    try:
        ctx = mp.get_context("spawn")
        stop_event = ctx.Event()
        simulation_queue = ctx.Queue()

        is_current_varying = is_current_varying_simulation(config)
        target_fn = (
            init_current_varying_simulation
            if is_current_varying
            else init_frequency_varying_simulation
        )

        _process = ctx.Process(
            target=target_fn,
            args=(
                model_id,
                config,
            ),
            kwargs={
                "access_token": access_token,
                "realtime": realtime,
                "simulation_queue": simulation_queue,
                "stop_event": stop_event,
                "project_context": project_context,
            },
        )

        _process.start()

        if realtime is True:
            return stream_realtime_data(
                simulation_queue=simulation_queue,
                _process=_process,
                is_current_varying=is_current_varying,
            )
    except Exception as ex:
        logger.exception(f"running simulation failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="running simulation failed",
            details=ex.__str__(),
        ) from ex
