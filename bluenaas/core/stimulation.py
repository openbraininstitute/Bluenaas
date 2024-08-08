# TODO: IMPORTANT: This methods is replicated from BlueCellab and any changes from the library should be updated here too

from __future__ import annotations
import queue
import neuron
import numpy as np
import multiprocessing as mp
from typing import Dict, NamedTuple, Sequence
from enum import Enum, auto

from bluecellulab.cell.core import Cell
from bluecellulab.cell.template import TemplateParams
from bluecellulab.simulation.simulation import Simulation
from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing
from bluecellulab.stimulus.factory import Stimulus, StimulusFactory
from bluecellulab.simulation.neuron_globals import NeuronGlobals

from bluenaas.utils.const import QUEUE_STOP_EVENT


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


def init_process_worker(neuron_global_params):
    """Load global parameters for the NEURON environment in each worker
    process."""
    NeuronGlobals.get_instance().load_params(neuron_global_params)


def run_stimulus(
    template_params: TemplateParams,
    stimulus: Stimulus,
    section: str,
    segment: float,
    simulation_queue: mp.Queue,
    stimulus_name: StimulusName,
    amplitude: float,
    cvode: bool = True,
    add_hypamp: bool = True,
) -> Recording:
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
    cell = Cell.from_template_parameters(template_params)
    neuron_section = cell.sections[section]
    if add_hypamp:
        hyp_stim = Hyperpolarizing(
            target="", delay=0.0, duration=stimulus.stimulus_time
        )
        cell.add_replay_hypamp(hyp_stim)
    cell.add_voltage_recording(neuron_section, segment)
    iclamp, _ = cell.inject_current_waveform(
        stimulus.time, stimulus.current, section=neuron_section, segx=segment
    )
    current_vector = neuron.h.Vector()
    current_vector.record(iclamp._ref_i)
    simulation = Simulation(cell)
    simulation.run(stimulus.stimulus_time, cvode=cvode)
    current = np.array(current_vector.to_python())
    voltage = cell.get_voltage_recording(neuron_section, segment)
    time = cell.get_time()

    if len(time) != len(voltage) or len(time) != len(current):
        raise ValueError("Time, current and voltage arrays are not the same length")

    recording = Recording(current, voltage, time)
    stimulus_name = f"{stimulus_name}_{amplitude}"

    simulation_queue.put(
        (
            stimulus_name,
            recording,
        )
    )

    return recording


def prepare_stimulation_parameters(
    cell: Cell,
    stimulus_name: StimulusName,
    simulation_queue: mp.Queue,
    amplitudes: Sequence[float],
    section_name: str | None = None,
    threshold_based: bool = True,
    segment: float = 0.5,
    cvode: bool = True,
    add_hypamp: bool = True,
):
    stim_factory = StimulusFactory(dt=1.0)
    task_args = []
    section_name = section_name if section_name is not None else "soma[0]"

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
        else:
            raise ValueError("Unknown stimulus name.")

        task_args.append(
            (
                cell.template_params,
                stimulus,
                section_name,
                segment,
                simulation_queue,
                stimulus_name,
                amplitude,
                cvode,
                add_hypamp,
            )
        )

    return task_args


def apply_multiple_stimulus(
    cell: Cell,
    stimulus_name: StimulusName,
    simulation_queue: mp.Queue,
    amplitudes: Sequence[float],
    req_id: str,
    section_name: str | None = None,
):
    stimulus_name_mapped = get_stimulus_name(stimulus_name)

    ctx = mp.get_context("fork")
    neuron_global_params = NeuronGlobals.get_instance().export_params()

    with mp.Manager() as manager:
        children_queue = manager.Queue()
        args = prepare_stimulation_parameters(
            cell=cell,
            stimulus_name=stimulus_name_mapped,
            amplitudes=amplitudes,
            section_name=section_name,
            simulation_queue=children_queue,
        )
        with ctx.Pool(
            processes=None,
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as pool:
            pool.starmap(run_stimulus, args)
            children_queue.put(QUEUE_STOP_EVENT)

        while True:
            try:
                record = children_queue.get()
            except queue.Empty:
                break

            if record == QUEUE_STOP_EVENT:
                break

            simulation_queue.put(record)

        simulation_queue.put(QUEUE_STOP_EVENT)


def run_synapse_simulation_in_child(
    template_params: TemplateParams,
    simulation_queue: mp.Queue,
) -> SynapseRecording:
    cell = Cell.from_template_parameters(template_params)

    sim = Simulation()
    sim.add_cell(cell)

    sim.run(160.0, cvode=False, dt=0.1)  # TODO: Synapse How to get duration
    time = cell.get_time()
    voltage = (
        cell.get_soma_voltage()
    )  # TODO: Get voltage from injectTo location chosen by user

    print("Time", time)
    print("Voltage", voltage)

    if len(time) != len(voltage):
        raise ValueError("Time and voltage arrays are not the same length")

    recording = SynapseRecording(
        voltage, time
    )  # TODO: How to get current like we get in directInjectionConfig

    simulation_queue.put(
        (
            "SynapseRecording",  # TODO: What name should this recording get?
            recording,
        )
    )
    return recording


def run_synpase_simulation(
    cell: Cell,
    parent_queue: mp.Queue,
):
    ctx = mp.get_context("fork")
    neuron_global_params = NeuronGlobals.get_instance().export_params()

    with mp.Manager() as manager:
        child_queue = manager.Queue()

        with ctx.Pool(
            processes=None,
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as pool:
            pool.starmap(
                run_synapse_simulation_in_child,
                [(cell.template_params, child_queue)],
            )
            child_queue.put(QUEUE_STOP_EVENT)

        while True:
            try:
                record = child_queue.get()
            except queue.Empty:
                break

            if record == QUEUE_STOP_EVENT:
                break

            parent_queue.put(record)

        parent_queue.put(QUEUE_STOP_EVENT)
