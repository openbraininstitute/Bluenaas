import json
from pathlib import Path
from celery import Celery
from loguru import logger
import numpy as np
from bluenaas.config.settings import settings
from bluenaas.core.stimulation.common import (
    StimulusName,
    _add_single_synapse,
    init_process_worker,
    is_current_varying_simulation,
)
from bluenaas.core.stimulation.runners import _init_current_varying_simulation, _init_frequency_varying_simulation
from bluenaas.utils.cpu_usage import get_cpus_in_use
from celery.worker.control import inspect_command
from bluenaas.utils.util import diff_list

from bluenaas.core.exceptions import (
    ChildSimulationError,
)
from bluenaas.domains.morphology import (
    SynapseSeries,
)
from bluenaas.domains.simulation import (
    ExperimentSetupConfig,
    RecordingLocation,
    SingleNeuronSimulationConfig,
)



celery_app = Celery(
    __name__,
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # worker_send_task_events=True,
    # task_track_started=True,
    # task_send_sent_event=True,
    # task_acks_late=True,
    # task_reject_on_worker_lost=True,
    result_compression="gzip",
    result_extended=True,
    database_table_names={
        "task": "simulations",
        "group": "grouped_simulations",
    },
)

# celery_worker = Celery(
#     __name__,
#     broker="redis://redis:6379/0",
#     backend="db+postgresql+psycopg2://postgres:password@db:5432/bleunaas",
#     result_compression="gzip",
# )


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
    import neuron
    from bluecellulab.cell.core import Cell
    from bluecellulab.simulation.simulation import Simulation
    from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing
    from bluecellulab.rngsettings import RNGSettings
    from bluecellulab.simulation.neuron_globals import NeuronGlobals

    neuron_global_params = NeuronGlobals.get_instance().export_params()
    init_process_worker(neuron_global_params)

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
            dt=experimental_setup.time_step,
            show_progress=True,
        )
        return final_result
    except Exception as ex:
        logger.exception(f"child simulation failed {ex}")
        raise ChildSimulationError from ex
    finally:
        logger.info("child simulation ended")


@inspect_command()
def cpu_usage_stats(state):
    return get_cpus_in_use()


@celery_app.task(bind=True)
def create_simulation(
    self,
    *,
    model_id: str,
    req_id: str,
    config: dict,
    token: str,
):
    cf = SingleNeuronSimulationConfig(**json.loads(config))
    is_current_varying = is_current_varying_simulation(cf)

    if is_current_varying:
        simulations = _init_current_varying_simulation(
            model_id,
            token,
            config=cf,
            req_id=req_id,
        )
        logger.info("@@@--------------------------")
        logger.info(f"@@simulations {simulations}")
        logger.info("@@@--------------------------")
        return {
            "model_id": model_id,
            "req_id": req_id,
            "config": config,
            "simulations": simulations,
        }
    else:
        _init_frequency_varying_simulation(
            model_id,
            token,
            config=cf,
            req_id=req_id,
        )