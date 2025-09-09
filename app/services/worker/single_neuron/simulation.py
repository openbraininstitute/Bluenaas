from itertools import chain
from typing import NamedTuple
from uuid import UUID

from loguru import logger

from app.core.exceptions import AppErrorCode, SimulationError
from app.core.job_stream import JobStream
from app.core.model import fetch_synaptome_model_details, model_factory
from app.domains.job import JobStatus
from app.domains.morphology import SynapseConfig, SynapseSeries, SynapsesPlacementConfig
from app.domains.simulation import SingleNeuronSimulationConfig, SynapseSimulationConfig
from app.external.entitycore.service import ProjectContext
from app.infrastructure.rq import get_job_stream_key
from app.utils.util import log_stats_for_series_in_frequency

# class ExpandedSimulationConfig(NamedTuple):
#     """Individual simulation configuration with single parameter values."""

#     base_config: SingleNeuronSimulationConfig
#     amplitude: float | None
#     frequency: float | None
#     synapse_generation_config: list[SynapseSeries] | None


# def expand_simulation_config(
#     config: SingleNeuronSimulationConfig,
#     synaptome_details=None,
#     model=None,
# ) -> list[ExpandedSimulationConfig]:
#     """Expand simulation config into individual configs with single parameter values."""
#     expanded_configs = []

#     if config.type == "single-neuron-simulation" or config.synaptome is None:
#         # Current varying simulation - expand amplitudes
#         amplitudes = config.current_injection.stimulus.amplitudes
#         if not isinstance(amplitudes, list):
#             amplitudes = [amplitudes]

#         for amplitude in amplitudes:
#             # Create modified config with single amplitude
#             modified_config = config.model_copy()
#             modified_config.current_injection.stimulus.amplitudes = amplitude

#             expanded_configs.append(
#                 ExpandedSimulationConfig(
#                     base_config=modified_config,
#                     amplitude=amplitude,
#                     frequency=None,
#                     synapse_generation_config=None,
#                 )
#             )
#     else:
#         # Synaptome simulation - check if frequency varying
#         has_frequency_varying = any(
#             isinstance(syn_config.frequency, list) for syn_config in config.synaptome
#         )

#         if not has_frequency_varying:
#             # Current varying with synapses
#             amplitudes = config.current_injection.stimulus.amplitudes
#             if not isinstance(amplitudes, list):
#                 amplitudes = [amplitudes]

#             synapse_generation_config = _create_synapse_config_for_current_varying(
#                 config, synaptome_details, model
#             )

#             for amplitude in amplitudes:
#                 modified_config = config.model_copy()
#                 modified_config.current_injection.stimulus.amplitudes = amplitude

#                 expanded_configs.append(
#                     ExpandedSimulationConfig(
#                         base_config=modified_config,
#                         amplitude=amplitude,
#                         frequency=None,
#                         synapse_generation_config=synapse_generation_config,
#                     )
#                 )
#         else:
#             # Frequency varying simulation
#             frequency_to_synapse_config = _create_frequency_to_synapse_config(
#                 config, synaptome_details, model
#             )

#             print(frequency_to_synapse_config)

#             amplitude = config.current_injection.stimulus.amplitudes
#             assert not isinstance(amplitude, list), (
#                 "Amplitude must be single value for frequency varying"
#             )

#             for frequency, synapse_config in frequency_to_synapse_config.items():
#                 expanded_configs.append(
#                     ExpandedSimulationConfig(
#                         base_config=config,
#                         amplitude=None,
#                         frequency=frequency,
#                         synapse_generation_config=synapse_config,
#                     )
#                 )

#     return expanded_configs


# def _create_synapse_config_for_current_varying(
#     config: SingleNeuronSimulationConfig,
#     synaptome_details,
#     model,
# ) -> list[SynapseSeries]:
#     """Create synapse configuration for current varying simulation."""
#     synapse_settings = []

#     synaptome = config.synaptome
#     if synaptome is None:
#         raise ValueError("Synaptome config is required")

#     for index, synapse_sim_config in enumerate(synaptome):
#         synapse_placement_config = [
#             placement_config
#             for placement_config in synaptome_details.synaptome_placement_config.config
#             if synapse_sim_config.id == placement_config.id
#         ][0]

#         assert not isinstance(synapse_sim_config.frequency, list)
#         synapses_per_grp = model.get_synapse_series(
#             synapse_placement_config=synapse_placement_config,
#             synapse_simulation_config=synapse_sim_config,
#             offset=index,
#             frequencies_to_apply=[synapse_sim_config.frequency],
#         )
#         synapse_settings.append(synapses_per_grp)

#     return list(chain.from_iterable(synapse_settings))


# def _create_frequency_to_synapse_config(
#     config: SingleNeuronSimulationConfig,
#     synaptome_details,
#     model,
# ) -> dict[float, list[SynapseSeries]]:
#     """Create frequency to synapse configuration mapping for frequency varying simulation."""
#     variable_frequency_sim_configs = []
#     constant_frequency_sim_configs = []

#     # Split simulation configs
#     synaptome = config.synaptome
#     if synaptome is None:
#         raise ValueError("Synaptome config is required for frequency varying simulation")

#     for syn_sim_config in synaptome:
#         if isinstance(syn_sim_config.frequency, list):
#             variable_frequency_sim_configs.append(syn_sim_config)
#         else:
#             constant_frequency_sim_configs.append(syn_sim_config)

#     frequency_to_synapse_settings = {}
#     offset = 0

#     for variable_frequency_sim_config in variable_frequency_sim_configs:
#         synapse_placement_config = _get_synapse_placement_config(
#             variable_frequency_sim_config.id,
#             synaptome_details.synaptome_placement_config,
#         )

#         frequency_list = variable_frequency_sim_config.frequency
#         if not isinstance(frequency_list, list):
#             frequency_list = [frequency_list]

#         for frequency in frequency_list:
#             frequency_to_synapse_settings[frequency] = []

#             frequencies_to_apply = _get_constant_frequencies_for_sim_id(
#                 variable_frequency_sim_config.id, constant_frequency_sim_configs
#             )
#             frequencies_to_apply.append(frequency)

#             # Add synapse series for this variable frequency
#             frequency_to_synapse_settings[frequency].extend(
#                 model.get_synapse_series(
#                     synapse_placement_config,
#                     variable_frequency_sim_config,
#                     offset,
#                     frequencies_to_apply,
#                 )
#             )
#             offset += 1

#             sim_id_to_configs = _get_sim_configs_by_synapse_id(constant_frequency_sim_configs)

#             # Add synapse series for constant frequencies of same synapse set
#             if variable_frequency_sim_config.id in sim_id_to_configs:
#                 for sim_config in sim_id_to_configs[variable_frequency_sim_config.id]:
#                     frequency_to_synapse_settings[frequency].extend(
#                         model.get_synapse_series(
#                             synapse_placement_config,
#                             sim_config,
#                             offset,
#                             frequencies_to_apply,
#                         )
#                     )
#                     offset += 1
#                 sim_id_to_configs.pop(variable_frequency_sim_config.id)

#             # Add synapse series for other synapse sets
#             for sim_id in sim_id_to_configs:
#                 sim_configs_for_set = sim_id_to_configs[sim_id]
#                 constant_frequencies_for_set = _get_constant_frequencies_for_sim_id(
#                     sim_id, sim_configs_for_set
#                 )
#                 placement_config_for_set = _get_synapse_placement_config(
#                     sim_id, synaptome_details.synaptome_placement_config
#                 )

#                 for sim_config in sim_configs_for_set:
#                     frequency_to_synapse_settings[frequency].extend(
#                         model.get_synapse_series(
#                             placement_config_for_set,
#                             sim_config,
#                             offset,
#                             constant_frequencies_for_set,
#                         )
#                     )
#                     offset += 1

#     # Log statistics
#     for frequency, synapse_settings in frequency_to_synapse_settings.items():
#         logger.debug(
#             f"Constructed {len(synapse_settings)} synapse series for frequency {frequency}"
#         )
#         log_stats_for_series_in_frequency(synapse_settings)

#     return frequency_to_synapse_settings


# def _get_constant_frequencies_for_sim_id(
#     synapse_set_id: str, constant_frequency_sim_configs: list[SynapseSimulationConfig]
# ) -> list[float]:
#     """Get constant frequencies for a synapse set ID."""
#     constant_frequencies = []
#     for sim_config in constant_frequency_sim_configs:
#         if sim_config.id == synapse_set_id and not isinstance(sim_config.frequency, list):
#             constant_frequencies.append(sim_config.frequency)
#     return constant_frequencies


# def _get_synapse_placement_config(
#     sim_id: str, placement_configs: SynapsesPlacementConfig
# ) -> SynapseConfig:
#     """Get synapse placement config by simulation ID."""
#     for placement_config in placement_configs.config:
#         if placement_config.id == sim_id:
#             return placement_config
#     raise Exception(f"No synaptome placement config was found with id {sim_id}")


# def _get_sim_configs_by_synapse_id(
#     sim_configs: list[SynapseSimulationConfig],
# ) -> dict[str, list[SynapseSimulationConfig]]:
#     """Group simulation configs by synapse ID."""
#     sim_id_to_sim_configs = {}
#     for sim_config in sim_configs:
#         if sim_config.id in sim_id_to_sim_configs:
#             sim_id_to_sim_configs[sim_config.id].append(sim_config)
#         else:
#             sim_id_to_sim_configs[sim_config.id] = [sim_config]
#     return sim_id_to_sim_configs


def run_simulation(
    model_id: UUID,
    config: SingleNeuronSimulationConfig,
    *,
    realtime: bool,
    access_token: str,
    project_context: ProjectContext,
):
    """Unified simulation runner that handles both current and frequency varying simulations."""
    job_stream = None

    try:
        # Determine model ID and fetch synaptome details if needed
        me_model_id = model_id
        synaptome_details = None

        if config.type == "synaptome-simulation" and config.synaptome is not None:
            synaptome_details = fetch_synaptome_model_details(
                bearer_token=access_token,
                model_id=model_id,
                project_context=project_context,
            )
            me_model_id = synaptome_details.base_model_id

        # Create model
        model = model_factory(
            me_model_id,
            hyamp=config.conditions.hypamp,
            access_token=access_token,
            project_context=project_context,
        )

        if not model.CELL:
            raise RuntimeError("Model not initialized")

        # Expand configuration into individual simulation configs
        expanded_configs = config.expand()

        # Set up job stream for realtime mode
        if realtime:
            stream_key = get_job_stream_key()
            job_stream = JobStream(stream_key)

        # Run unified simulation directly
        model.CELL.start_simulation(
            expanded_configs=expanded_configs,
            synaptome_details=synaptome_details,
            realtime=realtime,
            job_stream=job_stream,
        )

    except SimulationError as ex:
        logger.exception(f"Simulation executor error: {ex}")
        if realtime and job_stream:
            error_payload = {
                "error_code": AppErrorCode.SIMULATION_ERROR,
                "message": "Simulation failed",
                "details": str(ex),
            }
            job_stream.send_status(job_status=JobStatus.error, extra=str(error_payload))
        raise ex
    except Exception as ex:
        logger.exception(f"Simulation executor error: {ex}")
        if realtime and job_stream:
            error_payload = {
                "error_code": AppErrorCode.SIMULATION_ERROR,
                "message": "Simulation failed",
                "details": str(ex),
            }
            job_stream.send_status(job_status=JobStatus.error, extra=str(error_payload))
        raise SimulationError from ex
    finally:
        logger.info("Simulation executor ended")
