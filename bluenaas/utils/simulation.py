from typing import Optional
from bluenaas.domains.simulation import (
    SimulationType,
    NexusSimulationType,
    SimulationStatusResponse,
    SIMULATION_TYPE_MAP,
)


def get_simulation_type(simulation_resource: dict) -> SimulationType:
    if isinstance(simulation_resource["@type"], list):
        nexus_sim_type = [
            res_type
            for res_type in simulation_resource["@type"]
            if res_type == "SingleNeuronSimulation" or res_type == "SynaptomeSimulation"
        ][0]
    else:
        nexus_sim_type = simulation_resource["@type"]

    if nexus_sim_type in SIMULATION_TYPE_MAP:
        return SIMULATION_TYPE_MAP[nexus_sim_type]
    else:
        raise ValueError(f"Unsupported simulation type {nexus_sim_type}")


def get_nexus_simulation_type(sim_type: SimulationType) -> NexusSimulationType:
    sim_types_to_nexus_types = {v: k for k, v in SIMULATION_TYPE_MAP.items()}
    if sim_type in sim_types_to_nexus_types:
        return sim_types_to_nexus_types[sim_type]
    else:
        raise ValueError(f"Unsupported simulation type {sim_type}")


def to_simulation_response(
    encoded_simulation_id: str,
    simulation_resource: dict,
    me_model_self: str,
    synaptome_model_self: Optional[str],
    distribution: Optional[dict],
):
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
