from typing import Optional
from loguru import logger
from bluenaas.domains.simulation import SimulationType, SimulationStatusResponse
from bluenaas.core.exceptions import SimulationError


def get_simulation_type(simulation_resource: dict) -> SimulationType:
    if isinstance(simulation_resource["@type"], list):
        sim_type = [
            res_type
            for res_type in simulation_resource["@type"]
            if res_type == "SingleNeuronSimulation" or res_type == "SynaptomeSimulation"
        ][0]
    else:
        sim_type = simulation_resource["@type"]

    if sim_type == "SingleNeuronSimulation":
        return "single-neuron-simulation"
    if sim_type == "SynaptomeSimulation":
        return "synaptome-simulation"

    raise SimulationError(f"Unsupported simulation type {sim_type}")


def to_simulation_response(
    encoded_simulation_id: str,
    simulation_resource: dict,
    me_model_self: str,
    synaptome_model_self: Optional[str],
    distribution: Optional[dict],
):
    logger.debug(f"Sim resource {simulation_resource}")
    return SimulationStatusResponse(
        id=encoded_simulation_id,
        status=simulation_resource["status"],
        results=distribution["simulation"] if distribution is not None else None,
        # simulation details
        type=get_simulation_type(simulation_resource=simulation_resource),
        name=simulation_resource["name"],
        description=simulation_resource["description"],
        created_by=simulation_resource["_createdBy"],
        injection_location=simulation_resource["injectionLocation"],
        recording_location=simulation_resource["recordingLocation"],
        brain_location=simulation_resource["brainLocation"],
        simulation_config=distribution["config"] if distribution is not None else None,
        # Used model details
        me_model_self=me_model_self,
        synaptome_model_self=synaptome_model_self,
    )
