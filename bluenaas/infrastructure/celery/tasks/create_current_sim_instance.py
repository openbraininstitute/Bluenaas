import json
from loguru import logger
from typing import Any, Tuple

import numpy as np
from bluenaas.core.stimulation.utils import (
    add_single_synapse,
    get_stimulus_from_name,
    get_stimulus_name,
)

from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    ExperimentSetupConfig,
    RecordingLocation,
    SingleNeuronSimulationConfig,
)
from bluenaas.utils.serializer import (
    deserialize_template_params,
)
from bluenaas.infrastructure.celery import celery_app


def basic_simulation_config(
    template_params,
    config: SingleNeuronSimulationConfig,
    injection_section_name: str,
    injection_segment: float,
    recording_location: RecordingLocation,
    experimental_setup: ExperimentSetupConfig,
    amplitude: float,
    add_hypamp: bool = True,
):
    from bluecellulab.importer import neuron
    from bluecellulab import Cell
    from bluecellulab.stimulus.circuit_stimulus_definitions import Hyperpolarizing
    from bluecellulab.rngsettings import RNGSettings
    from bluecellulab.stimulus.factory import StimulusFactory

    rng = RNGSettings(
        base_seed=experimental_setup.seed,
        synapse_seed=experimental_setup.seed,
        stimulus_seed=experimental_setup.seed,
    )

    rng.set_seeds(
        base_seed=experimental_setup.seed,
    )

    cell = Cell.from_template_parameters(template_params)

    # injection_section = cell.sections[injection_section_name]

    # sec, seg = cell.sections[recording_location.section], recording_location.offset

    # cell.add_voltage_recording(
    #     section=sec,
    #     segx=seg,
    # )

    # protocol = config.current_injection.stimulus.stimulus_protocol
    # stimulus_name = get_stimulus_name(protocol)
    # stim_factory = StimulusFactory(dt=1.0)
    # stimulus = get_stimulus_from_name(
    #     stimulus_name,
    #     stim_factory,
    #     cell,
    #     None,
    #     amplitude,
    # )

    # iclamp, _ = cell.inject_current_waveform(
    #     stimulus.time,
    #     stimulus.current,
    #     section=injection_section,
    #     segx=injection_segment,
    # )

    # current_vector = neuron.h.Vector()
    # # current_vector.record(iclamp._ref_i)
    # current = np.array(current_vector.to_python())
    # neuron.h.v_init = experimental_setup.vinit
    # neuron.h.celsius = experimental_setup.celsius

    # if add_hypamp:
    #     hyp_stim = Hyperpolarizing(
    #         target="",
    #         delay=0.0,
    #         duration=stimulus.stimulus_time,
    #     )
    #     cell.add_replay_hypamp(hyp_stim)

    # return (current, cell)


def task(
    model_info: Tuple[Any, list[SynapseSeries]],
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    amplitude,
    injection_section_name,
    recording_location: RecordingLocation,
    injection_segment: float = 0.5,
    thres_perc=None,
    add_hypamp=True,
    enable_realtime=False,
):
    from bluecellulab.simulation.simulation import Simulation
    from bluecellulab.simulation.neuron_globals import NeuronGlobals

    neuron_global_params = NeuronGlobals.get_instance().export_params()
    NeuronGlobals.get_instance().load_params(neuron_global_params)

    cf = SingleNeuronSimulationConfig(**json.loads(config))
    rl = RecordingLocation(**json.loads(recording_location))

    (template_params, synapse_generation_config) = model_info
    tm = deserialize_template_params(template_params)

    logger.info(f"@@@{tm=}@@@")
    logger.info("@@@DONE@@@")

    basic_simulation_config(
        tm,
        config=cf,
        injection_section_name=injection_section_name,
        injection_segment=injection_segment,
        recording_location=rl,
        experimental_setup=cf.conditions,
        amplitude=amplitude,
        add_hypamp=add_hypamp,
    )
    logger.info("@@@DONE222@@@")
    # if synapse_generation_config is not None:
    #     for synapse in synapse_generation_config:
    #         assert isinstance(synapse["synapseSimulationConfig"].frequency, float)
    #         add_single_synapse(
    #             cell=cell,
    #             synapse=synapse,
    #             experimental_setup=config.conditions,
    #         )

    # simulation = Simulation(cell, custom_progress_function=None)

    # simulation.run(
    #     maxtime=cf.duration,
    #     show_progress=enable_realtime,
    #     dt=cf.conditions.time_step,
    #     cvode=False,
    # )


@celery_app.task(bind=True, serializer="json", queue="simulator")
def create_single_current_simulation(
    self,
    model_info: Tuple[Any, list[SynapseSeries]],
    *,
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    amplitude,
    injection_section_name,
    recording_location: RecordingLocation,
    injection_segment: float = 0.5,
    thres_perc=None,
    add_hypamp=True,
    enable_realtime=False,
):
    logger.info("----------------------")
    logger.info("[create_single_current_simulation]")
    logger.info(f"---- {amplitude=}----")
    logger.info(f"---- {self.request.id}----")
    logger.info(f"---- {self.request.hostname}----")
    logger.info("----------------------")
    import billiard as brd

    task(
        model_info,
        model_self,
        token,
        config,
        amplitude,
        injection_section_name,
        recording_location,
        injection_segment,
        thres_perc,
        add_hypamp,
        enable_realtime,
    )
    # with brd.pool.Pool(
    #     processes=1,
    #     maxtasksperchild=1,
    # ) as pool:
    #     pool.starmap(
    #         task,
    #         iterable=[
    #             (
    #                 model_info,
    #                 model_self,
    #                 token,
    #                 config,
    #                 amplitude,
    #                 injection_section_name,
    #                 recording_location,
    #                 injection_segment,
    #                 thres_perc,
    #                 add_hypamp,
    #                 enable_realtime,
    #             )
    #         ],
    #     )