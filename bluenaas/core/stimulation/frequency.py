# TODO: IMPORTANT: This methods is replicated from BlueCellab and any changes from the library should be updated here too

from __future__ import annotations
import os
from loguru import logger
import neuron
import numpy as np
import multiprocessing as mp
from bluenaas.core.exceptions import ChildSimulationError
from bluenaas.core.stimulation import StimulusName
from bluenaas.core.stimulation.common import (
    DEFAULT_INJECTION_LOCATION,
    _add_single_synapse,
    get_stimulus_from_name,
    get_stimulus_name,
    init_process_worker,
)
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    CurrentInjectionConfig,
    RecordingLocation,
    ExperimentSetupConfig,
)
from bluenaas.utils.util import (
    diff_list,
)


def _run_frequency_varying_stimulus(
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
    frequency: float,
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

    def enqueue_simulation_recordings():
        for loc in recording_locations:
            sec, seg = cell.sections[loc.section], loc.offset
            cell_section = f"{loc.section}_{seg}"
            stim_label = f"Frequency_{frequency}"

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

            # simulation_queue.put(
            #     (
            #         stim_label,
            #         cell_section,
            #         amplitude,
            #         frequency,
            #         Recording(
            #             current,
            #             voltage_diff,
            #             time_diff,
            #         ),
            #     )
            # )

    try:
        simulation = Simulation(
            cell,
            custom_progress_function=enqueue_simulation_recordings,
        )

        simulation.run(
            maxtime=simulation_duration,
            cvode=False,
            dt=experimental_setup.time_step,
            show_progress=True,
        )
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    # finally:
    #     simulation_queue.put(SUB_PROCESS_STOP_EVENT)


def _prepare_stimulation_parameters_by_frequency(
    cell,
    current_injection: CurrentInjectionConfig | None,
    recording_locations: list[RecordingLocation],
    frequency_to_synapse_series: dict[float, list[SynapseSeries]],
    conditions: ExperimentSetupConfig,
    simulation_duration: int,
    simulation_queue: mp.Queue,
    threshold_based: bool = False,
    injection_segment: float = 0.5,
    cvode: bool = True,
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

    assert current_injection is not None

    protocol = current_injection.stimulus.stimulusProtocol
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
                stimulus_name,
                amplitude,
                frequency,
                cvode,
                add_hypamp,
            )
        )
    return task_args


def apply_multiple_frequency(
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    experiment_setup: ExperimentSetupConfig,
    simulation_duration: int,
    frequency_to_synapse_series: dict[float, list[SynapseSeries]],
    # simulation_queue: mp.Queue,
    req_id: str,
):
    from bluecellulab.simulation.neuron_globals import NeuronGlobals

    ctx = mp.get_context("fork")
    neuron_global_params = NeuronGlobals.get_instance().export_params()

    logger.info(f"""
        Running Simulation of {req_id}
        {"CurrentInjection" if current_injection is not None else ""}
        {"Synaptome "}
    """)
    logger.info(f"[simulation duration]: {simulation_duration}")

    with mp.Manager() as manager:
        sub_simulation_queue = manager.Queue()

        args = _prepare_stimulation_parameters_by_frequency(
            cell=cell,
            current_injection=current_injection,
            recording_locations=recording_locations,
            frequency_to_synapse_series=frequency_to_synapse_series,
            conditions=experiment_setup,
            simulation_duration=simulation_duration,
            # simulation_queue=sub_simulation_queue,
        )

        logger.debug(f"Applying simulation for {len(args)} frequencies")

        with ctx.Pool(
            processes=min(len(args), os.cpu_count() or len(args)),
            initializer=init_process_worker,
            initargs=(neuron_global_params,),
            maxtasksperchild=1,
        ) as pool:
            pool.starmap_async(_run_frequency_varying_stimulus, args)

            # process_finished = 0

            # while True:
            #     try:
            #         record = sub_simulation_queue.get()
            #         if record != SUB_PROCESS_STOP_EVENT:
            #             simulation_queue.put(record)
            #         else:
            #             process_finished += 1
            #             if process_finished == len(args):
            #                 simulation_queue.put(QUEUE_STOP_EVENT)
            #                 break
            #     except queue.Empty:
            #         simulation_queue.put(QUEUE_STOP_EVENT)
            #         break
