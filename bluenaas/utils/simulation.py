from typing import Optional
from urllib.parse import quote_plus

from bluenaas.domains.nexus import (
    NexusBaseResource,
    FullNexusSimulationResource,
)
from bluenaas.domains.simulation import (
    SimulationType,
    NexusSimulationType,
    SimulationDetailsResponse,
    SingleNeuronSimulationConfig,
    SIMULATION_TYPE_MAP,
    BrainRegion,
)


def get_simulation_type(
    simulation_resource: NexusBaseResource,
) -> SimulationType:
    if isinstance(simulation_resource.type, list):
        nexus_sim_type = [
            res_type
            for res_type in simulation_resource.type
            if res_type == "SingleNeuronSimulation" or res_type == "SynaptomeSimulation"
        ][0]
    else:
        nexus_sim_type = simulation_resource.type

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


def convert_to_simulation_response(
    simulation_uri: str,
    simulation_resource: FullNexusSimulationResource,
    me_model_self: str,
    synaptome_model_self: Optional[str],
    simulation_config: Optional[SingleNeuronSimulationConfig],
    results: Optional[dict],
):
    brain_region = simulation_resource.brainLocation.get("brainRegion")
    return SimulationDetailsResponse(
        # Main info
        id=quote_plus(simulation_uri),
        status=simulation_resource.status,
        results=results,
        # Simulation metadata
        type=get_simulation_type(simulation_resource),
        name=simulation_resource.name,
        description=simulation_resource.description,
        created_by=simulation_resource.createdBy,
        created_at=simulation_resource.createdAt,
        injection_location=simulation_resource.injectionLocation,
        recording_location=simulation_resource.recordingLocation,
        brain_region=BrainRegion(id=brain_region["@id"], label=brain_region["label"]),
        config=simulation_config,
        # Used model details
        me_model_id=me_model_self,
        synaptome_model_id=synaptome_model_self,
    )


def get_simulations_by_recoding_name(simulations: list) -> dict[str, list]:
    record_location_to_simulation_result: dict[str, list] = {}

    # Iterate over simulation result for each current/frequency
    for trace in simulations:
        # For a given current/frequency, gather data for different recording locations
        for recording_name in trace:
            if recording_name not in record_location_to_simulation_result:
                record_location_to_simulation_result[recording_name] = []

            record_location_to_simulation_result[recording_name].append(
                {
                    "label": trace[recording_name]["label"],
                    "amplitude": trace[recording_name]["amplitude"],
                    "frequency": trace[recording_name]["frequency"],
                    "recording": trace[recording_name]["recording_name"],
                    "varying_key": trace[recording_name]["varying_key"],
                    "type": "scatter",
                    "t": trace[recording_name]["time"],
                    "v": trace[recording_name]["voltage"],
                }
            )

    return record_location_to_simulation_result
