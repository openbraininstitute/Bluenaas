from http import HTTPStatus
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.domains.simulation import SimulationStatusResponse
from loguru import logger
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
)


def fetch_simulation_status_and_results(
    token: str, org_id: str, project_id: str, simulation_id: str
) -> SimulationStatusResponse:
    try:
        nexus_helper = Nexus(
            {"token": token, "model_self_url": simulation_id}
        )  # TODO: Remove model_id as a required field for nexus helper

        simulation_resource = nexus_helper.fetch_resource_for_org_project(
            org_label=org_id, project_label=project_id, resource_id=simulation_id
        )
        used_model = simulation_resource["used"]["@id"]

        if simulation_resource["@type"] == "SingleNeuronSimulation":
            me_model_self = nexus_helper.fetch_resource_by_id(used_model)["_self"]
            synaptome_model_self = None
        else:
            synaptome_model = nexus_helper.fetch_resource_by_id(used_model)
            synaptome_model_self = synaptome_model["_self"]
            me_model = nexus_helper.fetch_resource_by_id(synaptome_model["used"]["@id"])
            me_model_self = me_model["_self"]

        if simulation_resource["status"] != "SUCCESS":
            return SimulationStatusResponse(
                id=simulation_id,
                status=simulation_resource["status"],
                results=None,
                # simulation details
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
            id=simulation_id,
            status=simulation_resource["status"],
            results=results["simulation"],
            # simulation details
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
