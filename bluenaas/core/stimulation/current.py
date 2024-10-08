from __future__ import annotations
from typing import Any
from loguru import logger
from bluenaas.core.stimulation.utils import (
    StimulusName,
    add_single_synapse,
)
from bluenaas.core.stimulation.common import (
    prepare_stimulation_parameters,
    apply_multiple_simulations,
    basic_simulation_config,
    dispatch_simulation_result,
    run_simulation_without_partial_updates,
    apply_multiple_simulations_without_partial_updates,
)
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import (
    CurrentInjectionConfig,
    RecordingLocation,
    ExperimentSetupConfig,
)


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
    run_without_updates: bool = False,
    queue: Any | None = None,
):
    logger.info(f"""
        [run_without_updates]: {run_without_updates}
        [simulation stimulus/start]: {stimulus}
        [simulation injection_section_name (provided)]: {injection_section_name}
        [simulation recording_locations]: {recording_locations}
    """)

    (cell, current) = basic_simulation_config(
        template_params,
        stimulus,
        injection_section_name,
        injection_segment,
        recording_locations,
        experimental_setup,
        add_hypamp,
    )

    if synapse_generation_config is not None:
        for synapse in synapse_generation_config:
            # Frequency should be constant in current varying simulation
            # TODO: handle AssertionError in the upper function
            assert isinstance(synapse["synapseSimulationConfig"].frequency, float)
            add_single_synapse(
                cell=cell,
                synapse=synapse,
                experimental_setup=experimental_setup,
            )

    if run_without_updates is True:
        # TODO: Add args names
        return run_simulation_without_partial_updates(
            cell,
            queue,
            current,
            recording_locations,
            simulation_duration,
            experimental_setup.time_step,
            amplitude,
            None,
            "current",
            stimulus_name.name,
        )

    return dispatch_simulation_result(
        cell,
        queue,
        current,
        recording_locations,
        simulation_duration,
        experimental_setup.time_step,
        amplitude,
        None,
        "current",
        stimulus_name.name,
    )


def apply_multiple_stimulus(
    cell,
    current_injection: CurrentInjectionConfig,
    recording_locations: list[RecordingLocation],
    experiment_setup: ExperimentSetupConfig,
    simulation_duration: int,
    current_synapse_serires: list[SynapseSeries] | None,
    run_without_updates: bool = False,
):
    logger.info(f"""
        Running Simulation run_without_updates {run_without_updates} of:
        {"CurrentInjection" if current_injection is not None else ""}
        {"Synaptome " if current_synapse_serires is not None else ""}
    """)

    args = prepare_stimulation_parameters(
        cell=cell,
        current_injection=current_injection,
        recording_locations=recording_locations,
        frequency_to_synapse_series=None,
        current_synapse_serires=current_synapse_serires,
        conditions=experiment_setup,
        simulation_duration=simulation_duration,
        varying_type="current",
        run_without_updates=run_without_updates,
    )

    if run_without_updates:
        return apply_multiple_simulations_without_partial_updates(
            args=args, runner=_run_current_varying_stimulus
        )
    return apply_multiple_simulations(
        args=args,
        runner=_run_current_varying_stimulus,
    )
