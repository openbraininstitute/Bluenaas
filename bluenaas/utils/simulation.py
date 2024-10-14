from typing import Optional
from urllib.parse import unquote

from loguru import logger

from bluenaas.domains.nexus import NexusSimulationResource
from bluenaas.domains.simulation import (
    SimulationType,
    NexusSimulationType,
    SimulationResultItemResponse,
    SIMULATION_TYPE_MAP,
)


def get_simulation_type(
    simulation_resource: NexusSimulationResource,
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
    simulation_resource: NexusSimulationResource,
    me_model_self: str,
    synaptome_model_self: Optional[str],
    distribution: Optional[dict],
):
    logger.info(f"[to_simulation_response] {simulation_resource}")
    return SimulationResultItemResponse(
        id=unquote(simulation_uri),
        self_uri=simulation_resource.self,
        name=simulation_resource.name,
        description=simulation_resource.description,
        type=get_simulation_type(simulation_resource),
        status=simulation_resource.status,
        created_by=simulation_resource.createdBy,
        created_at=simulation_resource.createdAt,
        results=distribution["simulation"] if distribution is not None else None,
        # simulation details
        injection_location=simulation_resource.injectionLocation,
        recording_location=simulation_resource.recordingLocation,
        brain_location=simulation_resource.brainLocation,
        config=distribution["config"] if distribution is not None else None,
        # Used model details
        me_model_self=me_model_self,
        synaptome_model_self=synaptome_model_self,
    )
