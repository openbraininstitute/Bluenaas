# TODO: IMPORTANT: This methods is replicated from BlueCellab and any changes from the library should be updated here too

from __future__ import annotations

import multiprocessing as mp
import os
import queue
from enum import Enum, auto
from multiprocessing.synchronize import Event
from queue import Queue
from typing import Any, Dict, NamedTuple

import neuron
import numpy as np
from loguru import logger

from app.core.exceptions import ChildSimulationError
from app.domains.morphology import SynapseSeries
from app.domains.simulation import (
    CurrentInjectionConfig,
    ExperimentSetupConfig,
    RecordingLocation,
)
from app.utils.const import QUEUE_STOP_EVENT, SUB_PROCESS_STOP_EVENT
from app.utils.util import (
    diff_list,
    generate_pre_spiketrain,
)

DEFAULT_INJECTION_LOCATION = "soma[0]"


class Recording(NamedTuple):
    """A tuple of the current, voltage and time recordings."""

    current: np.ndarray
    voltage: np.ndarray
    time: np.ndarray


class SynapseRecording(NamedTuple):
    """A tuple of the current, voltage and time recordings."""

    voltage: np.ndarray
    time: np.ndarray


class StimulusName(Enum):
    """Allowed values for the StimulusName."""

    AP_WAVEFORM = auto()
    IDREST = auto()
    IV = auto()
    FIRE_PATTERN = auto()
    POS_CHEOPS = auto()
    NEG_CHEOPS = auto()


StimulusRecordings = Dict[str, Recording]


def is_valid_stimuls_result(value):
    """Checks if the given value is a tuple of (str, Recording).

    Args:
      value: The value to check.

    Returns:
      True if the value is a valid tuple, False otherwise.
    """

    if not isinstance(value, tuple) or len(value) != 2:
        return False

    key, recording = value
    return isinstance(key, str) and isinstance(recording, Recording)


def get_stimulus_name(protocol_name):
    protocol_mapping = {
        "ap_waveform": StimulusName.AP_WAVEFORM,
        "idrest": StimulusName.IDREST,
        "iv": StimulusName.IV,
        "fire_pattern": StimulusName.FIRE_PATTERN,
    }

    if protocol_name not in protocol_mapping:
        raise Exception("Protocol does not have StimulusName assigned")

    return protocol_mapping[protocol_name]


def _create_recording_data(
    label: str,
    recording_name: str,
    time_data: np.ndarray,
    values_data: np.ndarray,
    variable_name: str,
    unit: str,
    amplitude: float | None = None,
    frequency: float | None = None,
) -> dict[str, Any]:
    """Create standardized recording data dictionary for queue."""
    return {
        "label": label,
        "recording_name": recording_name,
        "time_data": time_data.tolist(),
        "values_data": values_data.tolist(),
        "variable_name": variable_name,
        "unit": unit,
        "amplitude": amplitude,
        "frequency": frequency,
    }


def init_process_worker(neuron_global_params):
    """Load global parameters for the NEURON environment in each worker
    process."""
    from bluecellulab.simulation.neuron_globals import NeuronGlobals

    NeuronGlobals.get_instance().load_params(neuron_global_params)


def _add_single_synapse(
    cell,
    synapse: SynapseSeries,
    experimental_setup: ExperimentSetupConfig,
):
    from bluecellulab import Connection
    from bluecellulab.circuit.config.sections import Conditions  # type: ignore
    from bluecellulab.synapse.synapse_types import SynapseID  # type: ignore

    try:
        condition_parameters = Conditions(
            celsius=experimental_setup.celsius,
            v_init=experimental_setup.vinit,
            randomize_gaba_rise_time=True,
        )
        synid = SynapseID(f"{synapse['id']}", synapse["id"])
        # A tuple containing source and target popids used by the random number generation.

        # Should correspond to source_popid and target_popid
        popids = (2126, 378)
        connection_modifiers = {
            "add_synapses": True,
        }

        cell.add_replay_synapse(
            synapse_id=synid,
            syn_description=synapse["series"],
            connection_modifiers=connection_modifiers,
            condition_parameters=condition_parameters,
            popids=popids,
            extracellular_calcium=None,  # may not be value used in circuit
        )

        cell_synapse = cell.synapses[synid]
        spike_train = generate_pre_spiketrain(
            duration=synapse["synapseSimulationConfig"].duration,
            delay=synapse["synapseSimulationConfig"].delay,
            frequencies=synapse["frequencies_to_apply"],
        )
        spike_threshold = -900.0  # TODO: Synapse - How to get spike threshold
        connection = Connection(
            cell_synapse,
            pre_spiketrain=None if len(spike_train) == 0 else spike_train,
            pre_cell=None,
            stim_dt=cell.record_dt,
            spike_threshold=spike_threshold,
            spike_location="soma[0]",
        )
        cell.connections[synid] = connection
    except Exception:
        raise RuntimeError("Model not initialized")


def _prepare_stimulation_parameters_by_current(
    realtime: bool,
    cell,
    current_injection: CurrentInjectionConfig | None,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    conditions: ExperimentSetupConfig,
    simulation_duration: int,
    simulation_queue: Queue[Any],  # TODO Type narrow the queue
    threshold_based: bool = False,
    injection_segment: float = 0.5,
    cvode: bool = True,
    add_hypamp: bool = True,
):
    from bluecellulab.stimulus.factory import StimulusFactory

    stim_factory = StimulusFactory(dt=1.0)
    task_args = []

    injection_section_name = (
        current_injection.inject_to
        if current_injection is not None and current_injection.inject_to is not None
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
                simulation_queue,
                None,
                None,
                cvode,
                add_hypamp,
            )
        ]

    stimulus_name = current_injection.stimulus.stimulus_protocol
    amplitudes = current_injection.stimulus.amplitudes
    stimulus_name = get_stimulus_name(stimulus_name)

    if not isinstance(amplitudes, list):
        amplitudes = [amplitudes]

    stimulus = None

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
                realtime,
                cell.template_params,
                stimulus,
                injection_section_name,
                injection_segment,
                recording_locations,
                synapse_generation_config,
                conditions,
                simulation_duration,
                simulation_queue,
                stimulus_name,
                amplitude,
                cvode,
                add_hypamp,
            )
        )

    return task_args


def get_stimulus_from_name(stimulus_name: StimulusName, stimulus_factory, cell, thres_perc, amp):
    if stimulus_name == StimulusName.AP_WAVEFORM:
        return stimulus_factory.ap_waveform(
            threshold_current=cell.threshold,
            threshold_percentage=thres_perc,
            amplitude=amp,
        )
    elif stimulus_name == StimulusName.IDREST:
        return stimulus_factory.idrest(
            threshold_current=cell.threshold,
            threshold_percentage=thres_perc,
            amplitude=amp,
        )
    elif stimulus_name == StimulusName.IV:
        return stimulus_factory.iv(
            threshold_current=cell.threshold,
            threshold_percentage=thres_perc,
            amplitude=amp,
        )
    elif stimulus_name == StimulusName.FIRE_PATTERN:
        return stimulus_factory.fire_pattern(
            threshold_current=cell.threshold,
            threshold_percentage=thres_perc,
            amplitude=amp,
        )
    elif stimulus_name == StimulusName.POS_CHEOPS:
        return stimulus_factory.pos_cheops(
            threshold_current=cell.threshold,
            threshold_percentage=thres_perc,
            amplitude=amp,
        )
    elif stimulus_name == StimulusName.NEG_CHEOPS:
        return stimulus_factory.neg_cheops(
            threshold_current=cell.threshold,
            threshold_percentage=thres_perc,
            amplitude=amp,
        )


def _prepare_stimulation_parameters_by_frequency(
    realtime: bool,
    cell,
    current_injection: CurrentInjectionConfig | None,
    recording_locations: list[RecordingLocation],
    frequency_to_synapse_series: dict[float, list[SynapseSeries]],
    conditions: ExperimentSetupConfig,
    simulation_duration: int,
    simulation_queue: Queue[Any],  # TODO type
    threshold_based: bool = False,
    injection_segment: float = 0.5,
    cvode: bool = True,
    add_hypamp: bool = True,
):
    from bluecellulab.stimulus.factory import StimulusFactory

    stim_factory = StimulusFactory(dt=1.0)
    task_args = []

    injection_section_name = (
        current_injection.inject_to
        if current_injection is not None and current_injection.inject_to is not None
        else DEFAULT_INJECTION_LOCATION
    )

    assert current_injection is not None

    protocol = current_injection.stimulus.stimulus_protocol
    amplitude = current_injection.stimulus.amplitudes
    stimulus_name = get_stimulus_name(protocol)

    # Prepare arguments for each frequency
    for frequency in frequency_to_synapse_series:
        if threshold_based:
            thres_perc = amplitude
            amp = None
        else:
            thres_perc = None
            amp = amplitude

        stimulus = get_stimulus_from_name(stimulus_name, stim_factory, cell, thres_perc, amp)

        task_args.append(
            (
                realtime,
                cell.template_params,
                stimulus,
                injection_section_name,
                injection_segment,
                recording_locations,
                frequency_to_synapse_series[frequency],
                conditions,
                simulation_duration,
                simulation_queue,
                stimulus_name,
                amplitude,
                frequency,
                cvode,
                add_hypamp,
            )
        )
    return task_args


def _location_label(section: str, segment: float) -> str:
    return f"{section}_{segment}"


def _run_current_varying_stimulus(
    realtime: bool,
    template_params,
    stimulus,
    injection_section_name: str,
    injection_segment: float,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    experimental_setup: ExperimentSetupConfig,
    simulation_duration: int,
    simulation_queue: mp.Queue,
    stimulus_name: StimulusName,
    amplitude: float,
    cvode: bool = True,
    add_hypamp: bool = True,
):
    """Creates a cell and stimulates it with a given stimulus.

    Args:
        template_params: The parameters to create the cell from a template.
        stimulus: The input stimulus to inject into the cell.
        section: Name of the section of cell where the stimulus is to be injected.
        segment: The segment of the section where the stimulus is to be injected.
        cvode: True to use variable time-steps. False for fixed time-steps.

    Returns:
        The voltage-time recording at the specified location.

    Raises:
        ValueError: If the time and voltage arrays are not the same length.
    """

    from bluecellulab.cell.core import Cell
    from bluecellulab.rngsettings import RNGSettings
    from bluecellulab.simulation.simulation import Simulation
    from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing

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

    i_rec_var_dict = {}

    for loc in recording_locations:
        sec, seg = cell.sections[loc.section], loc.offset

        cell.add_variable_recording(
            "v",
            section=sec,
            segx=seg,
        )

        if loc.record_currents:
            location_label = _location_label(loc.section, loc.offset)
            i_rec_var_dict[location_label] = cell.add_currents_recordings(section=sec, segx=seg)

    iclamp, _ = cell.inject_current_waveform(
        stimulus.time,
        stimulus.current,
        section=injection_section,
        segx=injection_segment,
    )
    current_vector = neuron.h.Vector()
    current_vector.record(iclamp._ref_i)
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
    prev_current = {}

    def process_simulation_recordings(enable_realtime=True):
        for loc in recording_locations:
            sec, seg = cell.sections[loc.section], loc.offset
            location_label = _location_label(loc.section, loc.offset)
            label = f"{stimulus_name.name}_{amplitude}"

            voltage = cell.get_variable_recording("v", sec, seg)
            time = cell.get_time()

            if enable_realtime is True:
                if location_label not in prev_voltage:
                    prev_voltage[location_label] = np.array([])
                if location_label not in prev_time:
                    prev_time[location_label] = np.array([])

                voltage_diff = diff_list(prev_voltage[location_label], voltage)
                time_diff = diff_list(prev_time[location_label], time)

                prev_voltage[location_label] = voltage
                prev_time[location_label] = time

                simulation_queue.put(
                    _create_recording_data(
                        label=label,
                        recording_name=location_label,
                        time_data=time_diff,
                        values_data=voltage_diff,
                        variable_name="v",
                        unit="mV",
                        amplitude=amplitude,
                    )
                )

                for i_var_name in i_rec_var_dict.get(location_label, []):
                    if location_label not in prev_current:
                        prev_current[location_label] = {}

                    i_full_rec = cell.get_variable_recording(i_var_name, sec, seg)
                    i_diff = diff_list(
                        prev_current.get(location_label, {}).get(i_var_name, np.array([])),
                        i_full_rec,
                    )
                    prev_current[location_label][i_var_name] = i_full_rec

                    simulation_queue.put(
                        _create_recording_data(
                            label=label,
                            recording_name=location_label,
                            time_data=time_diff,
                            values_data=i_diff,
                            variable_name=i_var_name,
                            unit="mA/cm²",
                            amplitude=amplitude,
                        )
                    )
            else:
                simulation_queue.put(
                    _create_recording_data(
                        label=label,
                        recording_name=location_label,
                        time_data=time,
                        values_data=voltage,
                        variable_name="v",
                        unit="mV",
                        amplitude=amplitude,
                    )
                )

                for i_var_name in i_rec_var_dict.get(loc.section, []):
                    i_full_rec = cell.get_variable_recording(i_var_name, sec, seg)
                    simulation_queue.put(
                        _create_recording_data(
                            label=label,
                            recording_name=location_label,
                            time_data=time,
                            values_data=i_full_rec,
                            variable_name=i_var_name,
                            unit="mA/cm²",
                            amplitude=amplitude,
                        )
                    )

    try:
        simulation = Simulation(
            cell,
            custom_progress_function=process_simulation_recordings if realtime is True else None,
        )

        simulation.run(
            tstop=simulation_duration,
            cvode=False,
            dt=experimental_setup.time_step,
            show_progress=True if realtime is True else False,
        )

        if realtime is False:
            process_simulation_recordings(enable_realtime=False)
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    finally:
        simulation_queue.put(SUB_PROCESS_STOP_EVENT)


def _run_frequency_varying_stimulus(
    realtime: bool,
    template_params,
    stimulus,
    injection_section_name: str,
    injection_segment: float,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    experimental_setup: ExperimentSetupConfig,
    simulation_duration: int,
    simulation_queue: mp.Queue,
    stimulus_name: StimulusName,
    amplitude: float,
    frequency: float,
    cvode: bool = True,
    add_hypamp: bool = True,
):
    """Creates a cell and stimulates it with a given stimulus.

    Args:
        template_params: The parameters to create the cell from a template.
        stimulus: The input stimulus to inject into the cell.
        section: Name of the section of cell where the stimulus is to be injected.
        segment: The segment of the section where the stimulus is to be injected.
        cvode: True to use variable time-steps. False for fixed time-steps.

    Returns:
        The voltage-time recording at the specified location.

    Raises:
        ValueError: If the time and voltage arrays are not the same length.
    """

    logger.info(f"Starting simulation for frequency {frequency}")

    from bluecellulab.cell.core import Cell
    from bluecellulab.rngsettings import RNGSettings
    from bluecellulab.simulation.simulation import Simulation
    from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing

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
            _add_single_synapse(
                cell=cell,
                synapse=synapse,
                experimental_setup=experimental_setup,
            )

    i_rec_var_dict = {}

    for loc in recording_locations:
        sec, seg = cell.sections[loc.section], loc.offset

        cell.add_variable_recording(
            "v",
            section=sec,
            segx=seg,
        )

        if loc.record_currents:
            location_label = _location_label(loc.section, loc.offset)
            i_rec_var_dict[location_label] = cell.add_currents_recordings(section=sec, segx=seg)

    iclamp, _ = cell.inject_current_waveform(
        stimulus.time,
        stimulus.current,
        section=injection_section,
        segx=injection_segment,
    )
    current_vector = neuron.h.Vector()
    current_vector.record(iclamp._ref_i)
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
    prev_current = {}

    def process_simulation_recordings(enable_realtime=True):
        for loc in recording_locations:
            sec, seg = cell.sections[loc.section], loc.offset
            location_label = _location_label(loc.section, loc.offset)
            label = f"Frequency_{frequency}"

            voltage = cell.cell.get_variable_recording("v", sec, seg)
            time = cell.get_time()

            if enable_realtime:
                if location_label not in prev_voltage:
                    prev_voltage[location_label] = np.array([])
                if location_label not in prev_time:
                    prev_time[location_label] = np.array([])

                voltage_diff = diff_list(prev_voltage[location_label], voltage)
                time_diff = diff_list(prev_time[location_label], time)

                prev_voltage[location_label] = voltage
                prev_time[location_label] = time

                simulation_queue.put(
                    _create_recording_data(
                        label=label,
                        recording_name=location_label,
                        time_data=time_diff,
                        values_data=voltage_diff,
                        variable_name="v",
                        unit="mV",
                        amplitude=amplitude,
                        frequency=frequency,
                    )
                )

                for i_var_name in i_rec_var_dict.get(location_label, []):
                    if location_label not in prev_current:
                        prev_current[location_label] = {}

                    i_full_rec = cell.get_variable_recording(i_var_name, sec, seg)
                    i_diff = diff_list(
                        prev_current[location_label].get(i_var_name, np.array([])), i_full_rec
                    )
                    prev_current[location_label][i_var_name] = i_full_rec

                    simulation_queue.put(
                        _create_recording_data(
                            label=label,
                            recording_name=location_label,
                            time_data=time_diff,
                            values_data=i_diff,
                            variable_name=i_var_name,
                            unit="mA/cm²",
                            amplitude=amplitude,
                        )
                    )
            else:
                simulation_queue.put(
                    _create_recording_data(
                        label=label,
                        recording_name=location_label,
                        time_data=time,
                        values_data=voltage,
                        variable_name="v",
                        unit="mV",
                        amplitude=amplitude,
                        frequency=frequency,
                    )
                )

                for i_var_name in i_rec_var_dict.get(location_label, []):
                    i_full_rec = cell.get_variable_recording(i_var_name, sec, seg)
                    simulation_queue.put(
                        _create_recording_data(
                            label=label,
                            recording_name=location_label,
                            time_data=time,
                            values_data=i_full_rec,
                            variable_name=i_var_name,
                            unit="mA/cm²",
                            amplitude=amplitude,
                            frequency=frequency,
                        )
                    )

    try:
        simulation = Simulation(
            cell,
            custom_progress_function=process_simulation_recordings if realtime is True else None,
        )

        simulation.run(
            tstop=simulation_duration,
            cvode=False,
            dt=experimental_setup.time_step,
            show_progress=True if realtime is True else False,
        )

        if realtime is False:
            process_simulation_recordings(enable_realtime=False)
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    finally:
        simulation_queue.put(SUB_PROCESS_STOP_EVENT)


def apply_multiple_stimulus(
    realtime: bool,
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    experiment_setup: ExperimentSetupConfig,
    simulation_duration: int,
    synapse_generation_config: list[SynapseSeries] | None,
    simulation_queue: mp.Queue,
    stop_event: Event,
):
    from bluecellulab.simulation.neuron_globals import NeuronGlobals

    ctx = mp.get_context("fork")
    neuron_global_params = NeuronGlobals.get_instance().export_params()

    logger.info(f"""
        Running Simulation
        {"CurrentInjection" if current_injection is not None else ""}
        {"Synaptome " if synapse_generation_config is not None else ""}
    """)
    logger.info(f"[simulation duration]: {simulation_duration}")

    with mp.Manager() as manager:
        sub_simulation_queue = manager.Queue()

        args = _prepare_stimulation_parameters_by_current(
            realtime=realtime,
            cell=cell,
            current_injection=current_injection,
            recording_locations=recording_locations,
            synapse_generation_config=synapse_generation_config,
            conditions=experiment_setup,
            simulation_duration=simulation_duration,
            simulation_queue=sub_simulation_queue,
        )

        with ctx.Pool(
            processes=min(len(args), os.cpu_count() or len(args)),
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as pool:
            pool.starmap_async(_run_current_varying_stimulus, args)

            process_finished = 0

            while not stop_event.is_set():
                try:
                    record = sub_simulation_queue.get(timeout=1)
                    if record != SUB_PROCESS_STOP_EVENT:
                        simulation_queue.put(record)
                    else:
                        process_finished += 1
                        if process_finished == len(args):
                            break
                except queue.Empty:
                    continue

        # All child processes for simulations are done here.
        simulation_queue.put(QUEUE_STOP_EVENT)


def apply_multiple_frequency(
    realtime: bool,
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    experiment_setup: ExperimentSetupConfig,
    simulation_duration: int,
    frequency_to_synapse_series: dict[float, list[SynapseSeries]],
    simulation_queue: mp.Queue,
    stop_event: Event,
):
    from bluecellulab.simulation.neuron_globals import NeuronGlobals

    ctx = mp.get_context("fork")
    neuron_global_params = NeuronGlobals.get_instance().export_params()

    logger.info(f"""
        Running Simulation
        {"CurrentInjection" if current_injection is not None else ""}
        {"Synaptome "}
    """)
    logger.info(f"[simulation duration]: {simulation_duration}")

    with mp.Manager() as manager:
        sub_simulation_queue = manager.Queue()

        args = _prepare_stimulation_parameters_by_frequency(
            realtime=realtime,
            cell=cell,
            current_injection=current_injection,
            recording_locations=recording_locations,
            frequency_to_synapse_series=frequency_to_synapse_series,
            conditions=experiment_setup,
            simulation_duration=simulation_duration,
            simulation_queue=sub_simulation_queue,
        )

        logger.debug(f"Applying simulation for {len(args)} frequencies")

        with ctx.Pool(
            processes=min(len(args), os.cpu_count() or len(args)),
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as pool:
            pool.starmap_async(_run_frequency_varying_stimulus, args)

            process_finished = 0

            while not stop_event.is_set():
                try:
                    record = sub_simulation_queue.get(timeout=1)
                    if record != SUB_PROCESS_STOP_EVENT:
                        simulation_queue.put(record)
                    else:
                        process_finished += 1
                        if process_finished == len(args):
                            simulation_queue.put(QUEUE_STOP_EVENT)
                            break
                except queue.Empty:
                    continue

        # All child processes for simulations are done here.
        simulation_queue.put(QUEUE_STOP_EVENT)
