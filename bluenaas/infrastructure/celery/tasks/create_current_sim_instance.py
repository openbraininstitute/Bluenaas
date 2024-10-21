import json
import os
from loguru import logger
from typing import Any, Tuple

import numpy as np
from bluenaas.core.stimulation.common import setup_basic_simulation_config
from bluenaas.core.stimulation.utils import (
    add_single_synapse,
    get_stimulus_from_name,
    get_stimulus_name,
)

from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    ExperimentSetupConfig,
    RecordingLocation,
    SingleNeuronSimulationConfig,
)
from bluenaas.utils.serializer import (
    deserialize_template_params,
)
from bluenaas.infrastructure.celery import celery_app
from bluenaas.utils.util import locate_model


def task(
    model_info: Tuple[Any, list[SynapseSeries]],
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    amplitude,
    injection_section_name,
    recording_location: RecordingLocation,
    injection_segment: float = 0.5,
    thres_perc=None,
    add_hypamp=True,
    enable_realtime=False,
):
    from bluecellulab.simulation.simulation import Simulation
    

    cf = SingleNeuronSimulationConfig(**json.loads(config))
    rl = RecordingLocation(**json.loads(recording_location))

    (model_uuid, me_model_id, template_params, synapse_generation_config) = model_info
    tm = deserialize_template_params(template_params)

    # logger.info(f"@@@{tm=}@@@")
    # logger.info(f"@@@{model_uuid=}@@@")
    # os.chdir("/opt/blue-naas")
    # model_path = locate_model(model_uuid)
    # os.chdir(model_path)
    # logger.info(f"@@@{model_path=}@@@")
    # logger.info("@@@DONE@@@")
    setup_basic_simulation_config(
        tm,
        config=cf,
        injection_section_name=injection_section_name,
        injection_segment=injection_segment,
        recording_location=rl,
        experimental_setup=cf.conditions,
        amplitude=amplitude,
        add_hypamp=add_hypamp,
        me_model_id=me_model_id,
        token=token,
    )
    logger.info("@@@DONE222@@@")
    # if synapse_generation_config is not None:
    #     for synapse in synapse_generation_config:
    #         assert isinstance(synapse["synapseSimulationConfig"].frequency, float)
    #         add_single_synapse(
    #             cell=cell,
    #             synapse=synapse,
    #             experimental_setup=config.conditions,
    #         )

    # simulation = Simulation(cell, custom_progress_function=None)

    # simulation.run(
    #     maxtime=cf.duration,
    #     show_progress=enable_realtime,
    #     dt=cf.conditions.time_step,
    #     cvode=False,
    # )


@celery_app.task(bind=True, serializer="json", queue="simulator")
def create_single_current_simulation(
    self,
    model_info: Tuple[Any, list[SynapseSeries]],
    *,
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    amplitude,
    injection_section_name,
    recording_location: RecordingLocation,
    injection_segment: float = 0.5,
    thres_perc=None,
    add_hypamp=True,
    enable_realtime=False,
):
    logger.info("----------------------")
    logger.info("[create_single_current_simulation]")
    logger.info(f"---- {amplitude=}----")
    logger.info(f"---- {self.request.id}----")
    logger.info(f"---- {self.request.hostname}----")
    logger.info("----------------------")
    # import billiard as brd

    task(
        model_info,
        model_self,
        token,
        config,
        amplitude,
        injection_section_name,
        recording_location,
        injection_segment,
        thres_perc,
        add_hypamp,
        enable_realtime,
    )
    # with brd.pool.Pool(
    #     processes=1,
    #     maxtasksperchild=1,
    # ) as pool:
    #     pool.starmap(
    #         task,
    #         iterable=[
    #             (
    #                 model_info,
    #                 model_self,
    #                 token,
    #                 config,
    #                 amplitude,
    #                 injection_section_name,
    #                 recording_location,
    #                 injection_segment,
    #                 thres_perc,
    #                 add_hypamp,
    #                 enable_realtime,
    #             )
    #         ],
    #     )
