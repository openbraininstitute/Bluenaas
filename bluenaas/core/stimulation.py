# TODO: IMPORTANT: This methods is replicated from BlueCellab and any changes from the library should be updated here too

from __future__ import annotations
import queue
from loguru import logger
import neuron
import numpy as np
import multiprocessing as mp
from typing import Dict, NamedTuple
from enum import Enum, auto

from bluecellulab.cell.core import Cell
from bluecellulab.cell.template import TemplateParams
from bluecellulab.simulation.simulation import Simulation
from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing
from bluecellulab.stimulus.factory import Stimulus, StimulusFactory
from bluecellulab.simulation.neuron_globals import NeuronGlobals

from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    CurrentInjectionConfig,
    RecordingLocation,
    SimulationConditionsConfig,
)
from bluenaas.utils.const import QUEUE_STOP_EVENT
from bluenaas.utils.util import generate_pre_spiketrain

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


def init_process_worker(neuron_global_params):
    """Load global parameters for the NEURON environment in each worker
    process."""
    NeuronGlobals.get_instance().load_params(neuron_global_params)


def _add_single_synapse(
    cell, synapse: SynapseSeries, conditions: SimulationConditionsConfig
):
    from bluecellulab.circuit.config.sections import Conditions  # type: ignore
    from bluecellulab.synapse.synapse_types import SynapseID  # type: ignore
    from bluecellulab import Connection

    condition_parameters = Conditions(
        celsius=conditions.celsius,
        v_init=conditions.vinit,
        randomize_gaba_rise_time=True,
    )
    synid = SynapseID(f"{synapse["id"]}", synapse["id"])
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

    spike_train = generate_pre_spiketrain(synapse["synapseSimulationConfig"])
    spike_threshold = -900.0  # TODO: Synapse - How to get spike threshold
    connection = Connection(
        cell_synapse,
        pre_spiketrain=spike_train,
        pre_cell=None,
        stim_dt=cell.record_dt,
        spike_threshold=spike_threshold,
        spike_location="soma[0]",
    )
    cell.connections[synid] = connection


def _prepare_stimulation_parameters(
    cell: Cell,
    current_injection: CurrentInjectionConfig | None,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    conditions: SimulationConditionsConfig,
    simulation_queue: mp.Queue,
    threshold_based: bool = True,
    injection_segment: float = 0.5,
    cvode: bool = True,
    add_hypamp: bool = True,
):
    stim_factory = StimulusFactory(dt=1.0)
    task_args = []

    injection_section_name = (
        current_injection.injectTo
        if current_injection.injectTo is not None
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
                simulation_queue,
                None,
                None,
                cvode,
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
                simulation_queue,
                stimulus_name,
                amplitude,
                cvode,
                add_hypamp,
            )
        )

    return task_args


def _run_stimulus(
    template_params: TemplateParams,
    stimulus: Stimulus,
    injection_section_name: str,
    injection_segment: float,
    recording_locations: list[RecordingLocation],
    synapse_generation_config: list[SynapseSeries] | None,
    conditions: SimulationConditionsConfig,
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
    cell = Cell.from_template_parameters(template_params)
    injection_section = cell.sections[injection_section_name]

    if synapse_generation_config is not None:
        logger.info("---> synapse is here")
        for synapse in synapse_generation_config:
            _add_single_synapse(
                cell=cell,
                synapse=synapse,
                conditions=conditions,
            )

    for location in recording_locations:
        logger.info("---> add locations")
        recording_section = cell.sections[location.section]
        recording_segment = location.segment_offset

        cell.add_voltage_recording(
            section=recording_section,
            segx=recording_segment,
        )

    if stimulus is not None:
        logger.info("---> add iclamp, and hyp_Stim")
        iclamp, _ = cell.inject_current_waveform(
            stimulus.time,
            stimulus.current,
            section=injection_section,
            segx=injection_segment,
        )

        if add_hypamp:
            hyp_stim = Hyperpolarizing(
                target="",
                delay=0.0,
                duration=stimulus.stimulus_time,
            )
            cell.add_replay_hypamp(hyp_stim)

    current_vector = neuron.h.Vector()
    current_vector.record(iclamp._ref_i)
    simulation = Simulation(cell)
    logger.info(
        f"---> time of sim {stimulus.stimulus_time if stimulus is not None else conditions.max_time}"
    )

    simulation.run(
        maxtime=stimulus.stimulus_time if stimulus is not None else conditions.max_time,
        cvode=cvode,
    )

    current = np.array(current_vector.to_python())

    for location in recording_locations:
        recording_section = cell.sections[location.section]
        recording_segment = location.segment_offset

        voltage = cell.get_voltage_recording(
            section=recording_section,
            segx=recording_segment,
        )
        time = cell.get_time()

        recording = Recording(current, voltage, time)

        _stimulus_name = f"{stimulus_name.name}_{amplitude}"
        _recording_name = f"{location.section}_{recording_segment}"
        logger.info(
            f"---> end of chunk, stimulus_name: {_stimulus_name}, recording_name: {_recording_name}"
        )
        simulation_queue.put(
            (
                _stimulus_name,
                _recording_name,
                recording,
            )
        )


def apply_multiple_stimulus(
    cell: Cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    conditions: SimulationConditionsConfig,
    synapse_generation_config: list[SynapseSeries] | None,
    simulation_queue: mp.Queue,
    req_id: str,
):
    ctx = mp.get_context("fork")
    neuron_global_params = NeuronGlobals.get_instance().export_params()
    logger.debug(
        f'Running {req_id} \n {"Current Injection" if current_injection is not None else ""}, {"Synaptome " if synapse_generation_config is not None else ""}'
    )

    with mp.Manager() as manager:
        children_queue = manager.Queue()

        args = _prepare_stimulation_parameters(
            cell=cell,
            current_injection=current_injection,
            recording_locations=recording_locations,
            synapse_generation_config=synapse_generation_config,
            conditions=conditions,
            simulation_queue=children_queue,
        )
        with ctx.Pool(
            processes=None,
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as pool:
            pool.starmap(_run_stimulus, args)
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
