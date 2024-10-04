from __future__ import annotations
import os
import queue as que
from loguru import logger
import numpy as np
from typing import Literal
from bluenaas.core.exceptions import ChildSimulationError
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    CurrentInjectionConfig,
    ExperimentSetupConfig,
    RecordingLocation,
)
from bluenaas.utils.const import SUB_PROCESS_STOP_EVENT
from bluenaas.utils.util import diff_list
from bluenaas.core.stimulation.utils import (
    get_stimulus_from_name,
    get_stimulus_name,
    init_process_worker,
)

DEFAULT_INJECTION_LOCATION = "soma[0]"


def prepare_stimulation_parameters(
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    frequency_to_synapse_series: dict[float, list[SynapseSeries]] | None,
    current_synapse_serires: list[SynapseSeries] | None,
    conditions: ExperimentSetupConfig,
    simulation_duration: int,
    threshold_based: bool = False,
    injection_segment: float = 0.5,
    add_hypamp: bool = True,
    varying_type: Literal["frequency", "current"] = "current",
):
    from bluecellulab.stimulus.factory import StimulusFactory

    stim_factory = StimulusFactory(dt=1.0)
    task_args = []

    injection_section_name = (
        current_injection.injectTo
        if current_injection is not None and current_injection.injectTo is not None
        else DEFAULT_INJECTION_LOCATION
    )
    protocol = current_injection.stimulus.stimulusProtocol
    amplitudes = current_injection.stimulus.amplitudes
    stimulus_name = get_stimulus_name(protocol)

    # HERE: @dinika please confirm this is for both type of varying
    assert current_injection is not None
    if varying_type == "frequency":
        # Prepare arguments for each frequency
        for frequency in frequency_to_synapse_series:
            if threshold_based:
                thres_perc = amplitudes
                amp = None
            else:
                thres_perc = None
                amp = amplitudes

            stimulus = get_stimulus_from_name(
                stimulus_name, stim_factory, cell, thres_perc, amp
            )

            task_args.append(
                (
                    cell.template_params,
                    stimulus,
                    injection_section_name,
                    injection_segment,
                    recording_locations,
                    frequency_to_synapse_series[frequency],
                    conditions,
                    simulation_duration,
                    amplitudes,
                    frequency,
                    add_hypamp,
                )
            )
    elif varying_type == "current":
        for amplitude in amplitudes:
            if threshold_based:
                thres_perc = amplitude
                amp = None
            else:
                thres_perc = None
                amp = amplitude

            stimulus = get_stimulus_from_name(
                stimulus_name, stim_factory, cell, thres_perc, amp
            )

            task_args.append(
                (
                    cell.template_params,
                    stimulus,
                    injection_section_name,
                    injection_segment,
                    recording_locations,
                    current_synapse_serires,
                    conditions,
                    simulation_duration,
                    stimulus_name,
                    amplitude,
                    add_hypamp,
                )
            )

    return task_args


def basic_simulation_config(
    template_params,
    stimulus,
    injection_section_name: str,
    injection_segment: float,
    recording_locations: list[RecordingLocation],
    experimental_setup: ExperimentSetupConfig,
    add_hypamp: bool = True,
):
    import neuron
    from bluecellulab.cell.core import Cell
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

    return cell, current


def dispatch_simulation_result(
    cell,
    queue,
    current,
    recording_locations: list[RecordingLocation],
    simulation_duration: int,
    time_step: int,
    amplitude: float | None,
    frequency: float | None,
    varying_type: Literal["frequency", "current"],
    varying_key: str,
):
    from bluecellulab.simulation.simulation import Simulation

    prev_voltage = {}
    prev_time = {}
    final_result = {}

    def enqueue_simulation_recordings():
        for loc in recording_locations:
            sec, seg = cell.sections[loc.section], loc.offset
            cell_section = f"{loc.section}_{seg}"
            stim_label = f"{varying_key}_{frequency if varying_type == "frequency" else amplitude}"

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
                    "recording_name": cell_section,
                    "amplitude": amplitude,
                    "frequency": frequency,
                    "time": time.tolist(),
                    "current": time_diff.tolist(),
                    "voltage": voltage_diff.tolist(),
                    "varying_key": varying_key,
                }
            )

            final_result[cell_section] = {
                "stim_label": stim_label,
                "recording_name": cell_section,
                "amplitude": amplitude,
                "frequency": frequency,
                "time": time.tolist(),
                "current": current.tolist(),
                "voltage": voltage.tolist(),
                "varying_key": varying_key,
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
            dt=time_step,
        )
        return final_result
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    finally:
        logger.info("child simulation complete")
        queue.put(SUB_PROCESS_STOP_EVENT)


def apply_multiple_simulations(args, runner):
    from bluecellulab.simulation.neuron_globals import NeuronGlobals
    from celery import current_task, states
    from bluenaas.infrastructure.celery import celery_app
    import billiard as brd

    neuron_global_params = NeuronGlobals.get_instance().export_params()

    try:
        with brd.Manager() as manager:
            queue = manager.Queue()
            with brd.pool.Pool(
                processes=min(len(args), os.cpu_count() or len(args)),
                initializer=init_process_worker,
                initargs=(neuron_global_params,),
                maxtasksperchild=1,
            ) as pool:
                simulations = pool.starmap_async(
                    runner,
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
                                    "data": {
                                        "amplitude": record["amplitude"],
                                        "frequency": record["frequency"],
                                        "stimulus_name": record["stim_label"],
                                        "recording_name": record["recording_name"],
                                        "varying_key": record["varying_key"],
                                        "t": record["time"],
                                        "v": record["voltage"],
                                    }
                                },
                            )
                        else:
                            process_finished += 1
                            if process_finished == len(args):
                                current_task.update_state(
                                    state=states.SUCCESS,
                                    meta={"all_simulations_finished": True},
                                )
                                break
                    except que.Empty:
                        continue
                    except Exception as ex:
                        logger.exception(
                            f"Error during pulling simulation data from sub processes: {ex}"
                        )
                        current_task.update_state(
                            state=states.FAILURE,
                            meta={
                                "data": None,
                                "exit_due_exception": ex.__str__,
                            },
                        )
                        celery_app.control.revoke(
                            current_task.request.id, terminate=True
                        )
                return simulations.get()
    except Exception as e:
        logger.exception(f"Error during pool initialization or task submission: {e}")
        current_task.update_state(
            state=states.FAILURE,
            meta={
                "data": None,
                "exit_due_exception": e.__str__,
                "all_simulations_complete": False,
            },
        )
        celery_app.control.revoke(current_task.request.id, terminate=True)
