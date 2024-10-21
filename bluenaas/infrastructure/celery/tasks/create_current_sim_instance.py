import json
from typing import Any, Tuple

from loguru import logger
import numpy as np

from bluenaas.core.stimulation.common import setup_basic_simulation_config
from bluenaas.core.stimulation.utils import (
    add_single_synapse,
    get_stimulus_name,
    is_current_varying_simulation,
)

from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    RecordingLocation,
    SingleNeuronSimulationConfig,
)

from bluenaas.infrastructure.celery import celery_app
from bluenaas.utils.util import diff_list


def track_simulation_progress(
    cell,
    varying_key,
    varying_type,
    frequency,
    amplitude,
    location: RecordingLocation = None,
    enable_realtime=True,
    prev_voltage={},
    prev_time={},
    final_result={},
):
    from celery import current_task

    sec, seg = cell.sections[location.section], location.offset
    cell_section = f"{location.section}_{seg}"
    label = f"{varying_key}_{frequency if varying_type == "frequency" else amplitude}"

    voltage = cell.get_voltage_recording(sec, seg)
    time = cell.get_time()

    if enable_realtime:
        if cell_section not in prev_voltage:
            prev_voltage[cell_section] = np.array([])
        if cell_section not in prev_time:
            prev_time[cell_section] = np.array([])

        time_diff = diff_list(prev_time[cell_section], time)
        voltage_diff = diff_list(prev_voltage[cell_section], voltage)

        prev_voltage[cell_section] = voltage
        prev_time[cell_section] = time

        current_task.update_state(
            {
                "label": label,
                "recording": cell_section,
                "amplitude": amplitude,
                "frequency": frequency,
                "varying_key": frequency if varying_key == "frequency" else amplitude,
                "t": time_diff.tolist(),
                "v": voltage_diff.tolist(),
            }
        )

    final_result[cell_section] = {
        "label": label,
        "recording_name": cell_section,
        "amplitude": amplitude,
        "frequency": frequency,
        "time": time.tolist(),
        "voltage": voltage.tolist(),
        "varying_key": varying_key,
    }


@celery_app.task(
    bind=True,
    serializer="json",
    queue="simulator",
)
def create_single_current_simulation(
    self,
    model_info: Tuple[Any, list[SynapseSeries]],
    *,
    token: str,
    config: SingleNeuronSimulationConfig,
    amplitude: float,
    frequency: float,
    injection_section_name,
    recording_location: RecordingLocation,
    injection_segment: float = 0.5,
    thres_perc=None,
    add_hypamp=True,
    enable_realtime=False,
):
    logger.info(f"""
        [enable_realtime]: {enable_realtime}
        [simulation injection_section_name (provided)]: {injection_section_name}
        [simulation recording_location]: {recording_location}
    """)

    cf = SingleNeuronSimulationConfig(**json.loads(config))
    rl = RecordingLocation(**json.loads(recording_location))

    (
        me_model_id,
        template_params,
        synapse_generation_config,
        frequency_to_synapse_settings,
    ) = model_info
    (_, cell) = setup_basic_simulation_config(
        template_params,
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

    from bluecellulab.simulation.simulation import Simulation

    is_current_simulation = is_current_varying_simulation(config)
    protocol = config.current_injection.stimulus.stimulus_protocol
    stimulus_name = get_stimulus_name(protocol)
    
    if is_current_simulation:
        if synapse_generation_config is not None:
            for synapse in synapse_generation_config:
                assert isinstance(synapse["synapseSimulationConfig"].frequency, float)
                add_single_synapse(
                    cell=cell,
                    synapse=synapse,
                    experimental_setup=config.conditions,
                )
    else:
        if frequency_to_synapse_settings is not None:
            for synapse in frequency_to_synapse_settings:
                add_single_synapse(
                    cell=cell,
                    synapse=synapse,
                    experimental_setup=config.conditions,
                )


    prev_voltage = {}
    prev_time = {}
    final_result = {}

    Simulation(
        cell,
        custom_progress_function=lambda: track_simulation_progress(
            cell,
            varying_key=stimulus_name.name if is_current_simulation else "Frequency",
            varying_type="frequency" if is_current_simulation else "current",
            amplitude=amplitude,
            frequency=frequency,
            location=recording_location,
            enable_realtime=enable_realtime,
            prev_voltage=prev_voltage,
            prev_time=prev_time,
            final_result=final_result,
        )
        if enable_realtime
        else lambda: None,
    ).run(
        maxtime=cf.duration,
        show_progress=enable_realtime,
        dt=cf.conditions.time_step,
        cvode=False,
    )

    return final_result
