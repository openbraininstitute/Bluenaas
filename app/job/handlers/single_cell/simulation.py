import multiprocessing as mp
from http import HTTPStatus as status
from typing import Optional
from uuid import UUID

from loguru import logger

from app.core.exceptions import BlueNaasError, BlueNaasErrorCode
from app.domains.simulation import SingleNeuronSimulationConfig
from app.external.entitycore.service import ProjectContext
from app.external.nexus.nexus import Nexus
from app.services.worker.single_cell.simulation import (
    init_current_varying_simulation,
    init_frequency_varying_simulation,
    is_current_varying_simulation,
    save_simulation_result_to_nexus,
    stream_realtime_data,
)


def run_simulation(
    org_id: str,
    project_id: str,
    model_id: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    realtime: bool,
    simulation_resource_self: Optional[str] = None,
    entitycore: bool = False,
):
    nexus_helper = None
    try:
        if realtime is False and simulation_resource_self is not None:
            nexus_helper = Nexus({"token": token, "model_self_url": model_id})
            nexus_helper.update_simulation_status(
                org_id=org_id,
                project_id=project_id,
                resource_self=simulation_resource_self,
                status="started",
                is_draft=True,
            )

        ctx = mp.get_context("spawn")
        stop_event = ctx.Event()
        simulation_queue = ctx.Queue()

        is_current_varying = is_current_varying_simulation(config)

        project_context = None

        if entitycore:
            project_context = ProjectContext(
                virtual_lab_id=UUID(org_id),
                project_id=UUID(project_id),
            )

        _process = ctx.Process(
            target=init_current_varying_simulation
            if is_current_varying
            else init_frequency_varying_simulation,
            args=(
                model_id,
                token,
                config,
                realtime,
                simulation_queue,
                stop_event,
                entitycore,
                project_context,
            ),
        )

        _process.start()

        if realtime is True:
            return stream_realtime_data(
                simulation_queue=simulation_queue,
                _process=_process,
                is_current_varying=is_current_varying,
            )
        elif nexus_helper:
            assert simulation_resource_self is not None
            save_simulation_result_to_nexus(
                simulation_queue=simulation_queue,
                _process=_process,
                stop_event=stop_event,
                nexus_helper=nexus_helper,
                org_id=org_id,
                project_id=project_id,
                simulation_resource_self=simulation_resource_self,
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
