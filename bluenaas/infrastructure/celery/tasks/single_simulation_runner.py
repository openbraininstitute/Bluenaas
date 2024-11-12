"""
This task is responsible for running a single instance of a neuron simulation based on the type of variation.

Overview:
---------
- Executes a single simulation instance, varying either the current or the frequency, depending on the configuration.
- The recording location is also used to distinguish between different simulation instances.

"""

import json
from typing import Tuple
from loguru import logger
import numpy as np
from billiard import Process  # type: ignore

from bluenaas.core.stimulation.common import setup_basic_simulation_config
from bluenaas.core.stimulation.utils import (
    add_single_synapse,
    get_stimulus_name,
    is_current_varying_simulation,
)

from bluenaas.domains.simulation import (
    RecordingLocation,
    SingleNeuronSimulationConfig,
    SimulationStreamData,
    VaryingType,
)

from bluenaas.infrastructure.celery import celery_app
from bluenaas.infrastructure.celery.single_simulation_task_class import (
    SingleSimulationTask,
)
from bluenaas.utils.serializer import (
    deserialize_synapse_series_dict,
    deserialize_synapse_series_list,
)
from bluenaas.utils.util import diff_list


@celery_app.task(
    bind=True,
    serializer="json",
    base=SingleSimulationTask,
)
def single_simulation_runner(
    self,
    # NOTE: this tuple contains [me_model_i, template_params, synapse_generation_config, frequency_to_synapse_config]
    # in a serialized format
    model_info: Tuple[str, str, str, str],
    *,
    # NOTE: this need to be passed to be able to recover it in the celery task definition
    # and use it to save the simulation result
    org_id: str,
    project_id: str,
    resource_self: str | None,
    token: str,
    config: SingleNeuronSimulationConfig,
    amplitude: float,
    frequency: float,
    recording_location: RecordingLocation,
    injection_segment: float = 0.5,
    thres_perc=None,
    add_hypamp=True,
    realtime=False,
    autosave=False,
    channel_name=str,
):
    try:
        from celery import current_task  # type: ignore

        """
        NOTE: The simulation *needs* to run in a child process to allow the neuron simulator to be "reset" correctly.
        https://www.neuron.yale.edu/phpBB/viewtopic.php?t=4039
        
        If we don't run simulation in the child process then the simulator will return results for past simulation that were run in the worker also.
        """
        task_id = current_task.request.id
        process = Process(
            target=perform_simulation_work,
            args=(
                model_info,
                org_id,
                project_id,
                resource_self,
                token,
                config,
                amplitude,
                frequency,
                recording_location,
                injection_segment,
                thres_perc,
                add_hypamp,
                realtime,
                autosave,
                channel_name,
                task_id,
            ),
        )
        process.start()
        process.join()
        return "Simulation started in a separate process"

    except Exception as ex:
        logger.exception(f"running simulation failed in worker {ex}")


def perform_simulation_work(
    model_info: Tuple[str, str, str, str],
    # NOTE: this need to be passed to be able to recover it in the celery task definition
    # and use it to save the simulation result
    org_id: str,
    project_id: str,
    resource_self: str | None,
    token: str,
    config: str,  # string representing the json object of type SingleNeuronSimulationConfig
    amplitude: float,
    frequency: float,
    recording_location: str,  # string representing the json object of type RecordingLocation
    injection_segment: float,
    thres_perc: float | None,
    add_hypamp: bool,
    realtime: bool,
    autosave: bool,
    channel_name: str,
    task_id: str,
):
    from bluecellulab.simulation.simulation import Simulation  # type: ignore
    from bluenaas.infrastructure.redis import redis_client

    cf = SingleNeuronSimulationConfig(**json.loads(config))
    rl = RecordingLocation(**json.loads(recording_location))

    logger.debug(f"TYPE {type(thres_perc)} {thres_perc}")
    logger.info(f"""
        [enable_realtime]: {realtime}
        [amplitude]: {amplitude}
        [frequency]: {frequency}
        [simulation recording_location]: {recording_location}
    """)

    (
        me_model_id,
        template_params,
        synapse_generation_config,
        frequency_to_synapse_config,
    ) = model_info

    (_, cell) = setup_basic_simulation_config(
        template_params=template_params,
        config=cf,
        injection_segment=injection_segment,
        recording_location=rl,
        experimental_setup=cf.conditions,
        amplitude=amplitude,
        add_hypamp=add_hypamp,
        me_model_id=me_model_id,
        token=token,
        thres_perc=thres_perc,
    )

    protocol = cf.current_injection.stimulus.stimulus_protocol
    stimulus_name = get_stimulus_name(protocol)

    is_current_simulation = is_current_varying_simulation(cf)

    if is_current_simulation:
        if synapse_generation_config is not None:
            sgc = deserialize_synapse_series_list(synapse_generation_config)
            for synapse in sgc:
                assert isinstance(synapse["synapseSimulationConfig"].frequency, float)
                add_single_synapse(
                    cell=cell,
                    synapse=synapse,
                    experimental_setup=cf.conditions,
                )
    else:
        if frequency_to_synapse_config is not None:
            fsc = deserialize_synapse_series_dict(frequency_to_synapse_config)
            for synapse in fsc:
                add_single_synapse(
                    cell=cell,
                    synapse=synapse,
                    experimental_setup=cf.conditions,
                )

    sec, seg = cell.sections[rl.section], rl.offset

    cell_section = f"{rl.section}_{seg}"

    varying_key = stimulus_name.name if is_current_simulation else "frequency"
    varying_order = amplitude if is_current_simulation else frequency
    varying_type: VaryingType = "current" if is_current_simulation else "frequency"

    label = "{}_{}".format(
        varying_key,
        frequency if varying_type == "frequency" else amplitude,
    )

    prev_voltage = {}
    prev_time = {}
    final_result = {}

    def track_simulation_progress() -> None:
        logger.debug(
            f"Progress -> Task {task_id} Channel {channel_name} Type {varying_type} Order {varying_order} "
        )

        voltage = cell.get_voltage_recording(sec, seg)
        time = cell.get_time()

        if cell_section not in prev_voltage:
            prev_voltage[cell_section] = np.array([])
        if cell_section not in prev_time:
            prev_time[cell_section] = np.array([])

        time_diff = diff_list(prev_time[cell_section], time)
        voltage_diff = diff_list(prev_voltage[cell_section], voltage)

        prev_voltage[cell_section] = voltage
        prev_time[cell_section] = time

        partial_result: SimulationStreamData = {
            "state": "PROGRESS",
            "name": label,
            "recording": cell_section,
            "amplitude": amplitude,
            "frequency": frequency,
            "varying_key": varying_key,
            "varying_type": varying_type,
            "varying_order": varying_order,
            "x": time_diff.tolist(),
            "y": voltage_diff.tolist(),
        }

        redis_client.publish(channel_name, json.dumps(partial_result))

    simulation = Simulation(
        cell,
        custom_progress_function=track_simulation_progress if realtime else None,
    )

    simulation.run(
        maxtime=cf.duration,
        show_progress=realtime,
        dt=cf.conditions.time_step,
        cvode=False,
    )

    # NOTE: return result to be able to recover it
    # 1. when there is no realtime
    # 2. the user enable autosaving
    if not realtime:
        voltage = cell.get_voltage_recording(sec, seg)
        time = cell.get_time()

        final_result = {
            "label": label,
            "recording": cell_section,
            "amplitude": amplitude,
            "frequency": frequency,
            "t": time.tolist(),
            "v": voltage.tolist(),
            "varying_key": varying_key,
            "varying_type": varying_type,
            "varying_order": varying_order,
        }

    if realtime:
        redis_client.publish(channel_name, json.dumps({"state": "SUCCESS"}))
