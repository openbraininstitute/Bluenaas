from http import HTTPStatus
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.domains.simulation import SimulationStatusResponse, SimulationType
from urllib.parse import unquote
from loguru import logger
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode, SimulationError


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


def fetch_simulation_status_and_results(
    token: str, org_id: str, project_id: str, encoded_simulation_id: str
) -> SimulationStatusResponse:
    try:
        simulation_id = unquote(encoded_simulation_id)
        nexus_helper = Nexus(
            {"token": token, "model_self_url": simulation_id}
        )  # TODO: Remove model_id as a required field for nexus helper

        simulation_resource = nexus_helper.fetch_resource_for_org_project(
            org_label=org_id, project_label=project_id, resource_id=simulation_id
        )
        sim_type = get_simulation_type(simulation_resource)

        used_model_id = simulation_resource["used"]["@id"]
        if sim_type == "single-neuron-simulation":
            me_model_self = nexus_helper.fetch_resource_for_org_project(
                org_label=org_id, project_label=project_id, resource_id=used_model_id
            )["_self"]
            synaptome_model_self = None
        else:
            synaptome_model = nexus_helper.fetch_resource_for_org_project(
                org_label=org_id, project_label=project_id, resource_id=used_model_id
            )
            synaptome_model_self = synaptome_model["_self"]
            me_model = nexus_helper.fetch_resource_for_org_project(
                org_label=org_id,
                project_label=project_id,
                resource_id=synaptome_model["used"]["@id"],
            )
            me_model_self = me_model["_self"]

        if simulation_resource["status"] != "SUCCESS":
            return SimulationStatusResponse(
                id=encoded_simulation_id,
                status=simulation_resource["status"],
                results=None,
                # simulation details
                type=sim_type,
                simulation_config=None,
                name=simulation_resource["name"],
                description=simulation_resource["description"],
                created_by=simulation_resource["_createdBy"],
                # Used model details
                me_model_self=me_model_self,
                synaptome_model_self=synaptome_model_self,
            )

        file_url = simulation_resource["distribution"]["contentUrl"]
        file_response = nexus_helper.fetch_file_by_url(file_url)
        results = file_response.json()
        return SimulationStatusResponse(
            id=encoded_simulation_id,
            status=simulation_resource["status"],
            results=results["simulation"],
            # simulation details
            type=sim_type,
            simulation_config=results["config"],
            name=simulation_resource["name"],
            description=simulation_resource["description"],
            created_by=simulation_resource["_createdBy"],
            # Used model details
            me_model_self=me_model_self,
            synaptome_model_self=synaptome_model_self,
        )

    except Exception as ex:
        logger.exception(f"Error fetching simulation results {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            message="retrieving simulation data failed",
            details=ex.__str__(),
        ) from ex
