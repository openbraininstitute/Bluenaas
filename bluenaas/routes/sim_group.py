from typing import Any, Optional

from fastapi import APIRouter, Depends
from loguru import logger
from bluenaas.core.stimulation.common import DEFAULT_INJECTION_LOCATION
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    StreamSimulationBodyRequest,
)
from bluenaas.infrastructure.celery.tasks.create_current_sim_instance import (
    create_single_current_simulation,
)
from bluenaas.infrastructure.celery.tasks.initiate_simulation import initiate_simulation
from bluenaas.infrastructure.kc.auth import verify_jwt

router = APIRouter(
    prefix="/group",
    tags=["Group"],
)


def grouped_sim(
    org_id: str,
    project_id: str,
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    stimulus_plot_data: Optional[list[dict[str, Any]]] = None,
    simulation_resource: Optional[dict[str, Any]] = None,
    autosave: bool = False,
    enable_realtime: bool = True,
):
    from celery import group, chain

    logger.info(f"{config=}")
    injection_section_name = (
        config.current_injection.inject_to
        if config.current_injection is not None
        and config.current_injection.inject_to is not None
        else DEFAULT_INJECTION_LOCATION
    )

    amplitudes = config.current_injection.stimulus.amplitudes

    assert config.current_injection is not None
    instances = []

    for amplitude in amplitudes:
        for recording_location in config.record_from:
            instances.append(
                create_single_current_simulation.s(
                    token=token,
                    model_self=model_self,
                    amplitude=amplitude,
                    config=config.model_dump_json(),
                    recording_location=recording_location.model_dump_json(),
                    injection_section_name=injection_section_name,
                    injection_segment=0.5,
                    thres_perc=None,
                    add_hypamp=True,
                    enable_realtime=False,
                )
            )
    logger.info(f"--> {instances=}")
    job = initiate_simulation.s(
        model_self,
        token,
        config.model_dump_json(),
    ) | group(instances)
    result = job.apply_async()
    # while not result.ready():
    #     logger.info("@@--->")


@router.post(
    "/single-neuron/{org_id}/{project_id}/run-group",
    summary="Run neuron simulation realtime",
)
def execute_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    request: StreamSimulationBodyRequest,
    token: str = Depends(verify_jwt),
):
    return grouped_sim(
        org_id=org_id,
        token=token,
        project_id=project_id,
        model_self=model_self,
        config=request.config,
        autosave=request.autosave,
    )
