# NOTE: This file contains legacy functions that have been replaced by unified_simulation.py
# Most functions have been moved to unified_simulation.py to eliminate code duplication
# Some utility functions are kept here until all references are updated

from app.domains.simulation import SingleNeuronSimulationConfig


def is_current_varying_simulation(config: SingleNeuronSimulationConfig) -> bool:
    """Determine if simulation is current varying or frequency varying.
    
    NOTE: This function is kept for backward compatibility but the unified simulation
    approach in unified_simulation.py handles both types automatically.
    """
    if config.type == "single-neuron-simulation" or config.synaptome is None:
        return True

    synapse_set_with_multiple_frequency = [
        synapse_set for synapse_set in config.synaptome if isinstance(synapse_set.frequency, list)
    ]
    if len(synapse_set_with_multiple_frequency) > 0:
        # TODO: This assertion should be at pydantic model level
        assert not isinstance(config.current_injection.stimulus.amplitudes, list)
        return False

    return True
