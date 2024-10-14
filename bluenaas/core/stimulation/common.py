from __future__ import annotations
import os
import queue as que
from loguru import logger
from collections import namedtuple
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

TaskArgs = namedtuple(
    "TaskArgs",
    [
        "template_params",
        "stimulus",
        "injection_section_name",
        "injection_segment",
        "recording_locations",
        "synapse_series",
        "conditions",
        "simulation_duration",
        "stimulus_name_or_frequency",
        "amplitude_or_additional_param",
        "add_hypamp",
        "enable_realtime",
        "queue",
    ],
)


def prepare_stimulation_parameters(
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    frequency_to_synapse_series: dict[float, list[SynapseSeries]] | None,
    current_synapse_series: list[SynapseSeries] | None,
    conditions: ExperimentSetupConfig,
    simulation_duration: int,
    threshold_based: bool = False,
    injection_segment: float = 0.5,
    add_hypamp: bool = True,
    varying_type: Literal["frequency", "current"] = "current",
    enable_realtime: bool = True,
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
                TaskArgs(
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
                    enable_realtime,
                    None,
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
                TaskArgs(
                    cell.template_params,
                    stimulus,
                    injection_section_name,
                    injection_segment,
                    recording_locations,
                    current_synapse_series,
                    conditions,
                    simulation_duration,
                    stimulus_name,
                    amplitude,
                    add_hypamp,
                    enable_realtime,
                    None,
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
    enable_realtime: bool,
):
    from bluecellulab.simulation.simulation import Simulation

    prev_voltage = {}
    prev_time = {}
    final_result = {}

    def process_simulation_recordings(enable_realtime=True):
        for loc in recording_locations:
            sec, seg = cell.sections[loc.section], loc.offset
            cell_section = f"{loc.section}_{seg}"
            stim_label = f"{varying_key}_{frequency if varying_type == "frequency" else amplitude}"

            voltage = cell.get_voltage_recording(sec, seg)
            time = cell.get_time()

            if enable_realtime:
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
        if enable_realtime:
            simulation = Simulation(
                cell, custom_progress_function=process_simulation_recordings
            )

            simulation.run(
                maxtime=simulation_duration,
                cvode=False,
                show_progress=True,
                dt=time_step,
            )
        else:
            simulation = Simulation(cell)
            simulation.run(
                maxtime=simulation_duration,
                cvode=False,
                dt=time_step,
            )
            process_simulation_recordings(enable_realtime=False)

        return final_result
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    finally:
        logger.info("child simulation complete")
        queue.put(SUB_PROCESS_STOP_EVENT)


def apply_multiple_simulations(args, runner):
    import billiard as brd
    from celery import current_task, states
    from bluecellulab.simulation.neuron_globals import NeuronGlobals
    from bluenaas.infrastructure.celery import celery_app

    neuron_global_params = NeuronGlobals.get_instance().export_params()
    enable_realtime = all(arg.enable_realtime is True for arg in args)
    logger.debug(
        f"Parent process is about to start parallel simulations. enable_realtime {enable_realtime}"
    )
    try:
        with brd.Manager() as manager:
            queue = manager.Queue()
            with brd.pool.Pool(
                processes=min(len(args), os.cpu_count() or len(args)),
                initializer=init_process_worker,
                initargs=(neuron_global_params,),
                maxtasksperchild=1,
            ) as pool:
                if enable_realtime is True:
                    simulations = pool.starmap_async(
                        runner,
                        iterable=[
                            arg._replace(queue=queue) for arg in args
                        ],  # Add queue to arguments passed to `runner`
                    )
                else:
                    simulations = pool.starmap(
                        runner,
                        iterable=[
                            arg._replace(queue=queue) for arg in args
                        ],  # Add queue to arguments passed to `runner`
                    )

                process_finished = 0
                while True and enable_realtime:
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

                if enable_realtime:
                    return simulations.get()

                # In case of non_realtime updates simulations will be an array of sim results for different current/frequencies.
                return get_simulations_by_recoding_name(simulations=simulations)
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


def get_simulations_by_recoding_name(simulations: list) -> dict[str, list]:
    record_location_to_simulation_result: dict[str, list] = {}

    # Iterate over simulation result for each current/frequency
    for trace in simulations:
        # For a given current/frequency, gather data for different recording locations
        for recording_name in trace:
            if recording_name not in record_location_to_simulation_result:
                record_location_to_simulation_result[recording_name] = []

            record_location_to_simulation_result[recording_name].append(
                {
                    "x": trace[recording_name]["time"],
                    "y": trace[recording_name]["voltage"],
                    "type": "scatter",
                    "name": trace[recording_name]["stim_label"],
                    "recording": trace[recording_name]["recording_name"],
                    "amplitude": trace[recording_name]["amplitude"],
                    "frequency": trace[recording_name]["frequency"],
                    "varying_key": trace[recording_name]["varying_key"],
                }
            )
    return record_location_to_simulation_result
