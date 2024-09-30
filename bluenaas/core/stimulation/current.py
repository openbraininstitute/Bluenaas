from __future__ import annotations
import json
import os
import billiard as b
import queue as q
from typing import Any
from loguru import logger
import numpy as np
from bluenaas.core.exceptions import ChildSimulationError
from bluenaas.core.stimulation.common import (
    StimulusName,
    _add_single_synapse,
    init_process_worker,
)
from bluenaas.core.stimulation.common import (
    DEFAULT_INJECTION_LOCATION,
    get_stimulus_name,
)
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    CurrentInjectionConfig,
    RecordingLocation,
    ExperimentSetupConfig,
)
from bluenaas.utils.const import SUB_PROCESS_STOP_EVENT
from bluenaas.utils.util import diff_list


def _prepare_stimulation_parameters_by_current(
    cell,
    current_injection: CurrentInjectionConfig | None,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    conditions: ExperimentSetupConfig,
    simulation_duration: int,
    threshold_based: bool = False,
    injection_segment: float = 0.5,
    add_hypamp: bool = True,
):
    from bluecellulab.stimulus.factory import StimulusFactory

    stim_factory = StimulusFactory(dt=1.0)
    task_args = []

    injection_section_name = (
        current_injection.injectTo
        if current_injection is not None and current_injection.injectTo is not None
        else DEFAULT_INJECTION_LOCATION
    )

    if current_injection is None:
        return [
            (
                cell.template_params,
                None,
                injection_section_name,
                injection_segment,
                recording_locations,
                synapse_generation_config,
                conditions,
                simulation_duration,
                None,
                None,
                add_hypamp,
            )
        ]

    stimulus_name = current_injection.stimulus.stimulusProtocol
    amplitudes = current_injection.stimulus.amplitudes
    stimulus_name = get_stimulus_name(stimulus_name)

    # Prepare arguments for each stimulus
    for amplitude in amplitudes:
        if threshold_based:
            thres_perc = amplitude
            amp = None
        else:
            thres_perc = None
            amp = amplitude

        if stimulus_name == StimulusName.AP_WAVEFORM:
            stimulus = stim_factory.ap_waveform(
                threshold_current=cell.threshold,
                threshold_percentage=thres_perc,
                amplitude=amp,
            )
        elif stimulus_name == StimulusName.IDREST:
            stimulus = stim_factory.idrest(
                threshold_current=cell.threshold,
                threshold_percentage=thres_perc,
                amplitude=amp,
            )
        elif stimulus_name == StimulusName.IV:
            stimulus = stim_factory.iv(
                threshold_current=cell.threshold,
                threshold_percentage=thres_perc,
                amplitude=amp,
            )
        elif stimulus_name == StimulusName.FIRE_PATTERN:
            stimulus = stim_factory.fire_pattern(
                threshold_current=cell.threshold,
                threshold_percentage=thres_perc,
                amplitude=amp,
            )
        elif stimulus_name == StimulusName.POS_CHEOPS:
            stimulus = stim_factory.pos_cheops(
                threshold_current=cell.threshold,
                threshold_percentage=thres_perc,
                amplitude=amp,
            )
        elif stimulus_name == StimulusName.NEG_CHEOPS:
            stimulus = stim_factory.neg_cheops(
                threshold_current=cell.threshold,
                threshold_percentage=thres_perc,
                amplitude=amp,
            )

        task_args.append(
            (
                cell.template_params,
                stimulus,
                injection_section_name,
                injection_segment,
                recording_locations,
                synapse_generation_config,
                conditions,
                simulation_duration,
                stimulus_name,
                amplitude,
                add_hypamp,
            )
        )

    return task_args


def _run_current_varying_stimulus(
    template_params,
    stimulus,
    injection_section_name: str,
    injection_segment: float,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    experimental_setup: ExperimentSetupConfig,
    simulation_duration: int,
    stimulus_name: StimulusName,
    amplitude: float,
    add_hypamp: bool = True,
    queue: Any | None = None,
):
    logger.info(
        f"@@_run_current_varying_stimulus:  {stimulus} {injection_section_name} {injection_segment}"
    )
    logger.info(f"@@queue {queue} {type(queue)}")
    import neuron
    from bluecellulab.cell.core import Cell
    from bluecellulab.simulation.simulation import Simulation
    from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing
    from bluecellulab.rngsettings import RNGSettings

    rng = RNGSettings(
        base_seed=experimental_setup.seed,
        synapse_seed=experimental_setup.seed,
        stimulus_seed=experimental_setup.seed,
    )

    rng.set_seeds(
        base_seed=experimental_setup.seed,
    )

    cell = Cell.from_template_parameters(template_params)
    injection_section = cell.sections[injection_section_name]

    logger.info(f"""
        [simulation stimulus/start]: {stimulus}
        [simulation injection_section_name (provided)]: {injection_section_name}
        [simulation injection_section (resolved)]: {injection_section}
        [simulation recording_locations]: {recording_locations}
    """)

    if synapse_generation_config is not None:
        for synapse in synapse_generation_config:
            # Frequency should be constant in current varying simulation
            assert isinstance(synapse["synapseSimulationConfig"].frequency, float)
            _add_single_synapse(
                cell=cell,
                synapse=synapse,
                experimental_setup=experimental_setup,
            )

    for loc in recording_locations:
        sec, seg = cell.sections[loc.section], loc.offset

        cell.add_voltage_recording(
            section=sec,
            segx=seg,
        )

    iclamp, _ = cell.inject_current_waveform(
        stimulus.time,
        stimulus.current,
        section=injection_section,
        segx=injection_segment,
    )
    current_vector = neuron.h.Vector()
    current_vector.record(iclamp._ref_i)
    current = np.array(current_vector.to_python())
    neuron.h.v_init = experimental_setup.vinit
    neuron.h.celsius = experimental_setup.celsius

    if add_hypamp:
        hyp_stim = Hyperpolarizing(
            target="",
            delay=0.0,
            duration=stimulus.stimulus_time,
        )
        cell.add_replay_hypamp(hyp_stim)

    prev_voltage = {}
    prev_time = {}
    final_result = {}

    def enqueue_simulation_recordings():
        for loc in recording_locations:
            sec, seg = cell.sections[loc.section], loc.offset
            cell_section = f"{loc.section}_{seg}"
            stim_label = f"{stimulus_name.name}_{amplitude}"

            voltage = cell.get_voltage_recording(sec, seg)
            time = cell.get_time()

            if cell_section not in prev_voltage:
                prev_voltage[cell_section] = np.array([])
            if cell_section not in prev_time:
                prev_time[cell_section] = np.array([])

            voltage_diff = diff_list(prev_voltage[cell_section], voltage)
            time_diff = diff_list(prev_time[cell_section], time)

            prev_voltage[cell_section] = voltage
            prev_time[cell_section] = time

            queue.put(
                {
                    "stim_label": stim_label,
                    "amplitude": amplitude,
                    "time": time.tolist(),
                    "current": time_diff.tolist(),
                    "voltage": voltage_diff.tolist(),
                }
            )

            final_result[cell_section] = {
                "stim_label": stim_label,
                "amplitude": amplitude,
                "time": time.tolist(),
                "current": current.tolist(),
                "voltage": voltage.tolist(),
            }

    try:
        simulation = Simulation(
            cell,
            custom_progress_function=enqueue_simulation_recordings,
        )

        simulation.run(
            maxtime=simulation_duration,
            cvode=False,
            show_progress=True,
            dt=experimental_setup.time_step,
        )
        return final_result
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    finally:
        logger.info("child simulation ended")
        queue.put(SUB_PROCESS_STOP_EVENT)


def apply_multiple_stimulus(
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    experiment_setup: ExperimentSetupConfig,
    simulation_duration: int,
    synapse_generation_config: list[SynapseSeries] | None,
    req_id: str,
):
    from bluecellulab.simulation.neuron_globals import NeuronGlobals
    from celery import current_task, states

    neuron_global_params = NeuronGlobals.get_instance().export_params()

    logger.info(f"""
        Running Simulation of {req_id}
        {"CurrentInjection" if current_injection is not None else ""}
        {"Synaptome " if synapse_generation_config is not None else ""}
    """)

    args = _prepare_stimulation_parameters_by_current(
        cell=cell,
        current_injection=current_injection,
        recording_locations=recording_locations,
        synapse_generation_config=synapse_generation_config,
        conditions=experiment_setup,
        simulation_duration=simulation_duration,
    )
    try:
        manager = b.Manager()
        queue = manager.Queue()

        with b.pool.Pool(
            processes=min(len(args), os.cpu_count() or len(args)),
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as p:
            simulations = p.starmap_async(
                func=_run_current_varying_stimulus,
                iterable=[(*arg, queue) for arg in args],
            )

            process_finished = 0
            while True:
                try:
                    record = queue.get(timeout=1)
                    if record != SUB_PROCESS_STOP_EVENT:
                        current_task.update_state(
                            state="PROGRESS",
                            meta={
                                "data": json.dumps(record),
                                "all_processes_ends": False,
                                "queue_empty": False,
                            },
                        )
                    else:
                        process_finished += 1
                        if process_finished == len(args):
                            current_task.update_state(
                                state=states.SUCCESS,
                                meta={
                                    "data": None,
                                    "all_simulations_complete": True,
                                    "is_exit_due_queue_empty_exception": False,
                                },
                            )
                            break
                except q.Empty:
                    current_task.update_state(
                        state=states.SUCCESS,
                        meta={
                            "data": None,
                            "all_simulations_complete": False,
                            "is_exit_due_queue_empty_exception": True,
                        },
                    )
                    break

            return simulations.get()
    except Exception as e:
        current_task.update_state(
            state=states.FAILURE,
            meta={
                "data": None,
                "exit_due_exception": e.__str__,
                "all_simulations_complete": False,
                "is_exit_due_queue_empty_exception": True,
            },
        )
        logger.exception(f"Error during pool initialization or task submission: {e}")
