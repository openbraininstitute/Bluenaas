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

        if simulation_resource["status"] != "SUCCESS":
            return SimulationStatusResponse(
                id=simulation_id, status=simulation_resource["status"], results=None
            )

        file_url = simulation_resource["distribution"]["contentUrl"]
        file_response = nexus_helper.fetch_file_by_url(file_url)
        results = file_response.json()
        return SimulationStatusResponse(
            id=simulation_id,
            status=simulation_resource["status"],
            results=results["simulation"],
        )

    except Exception as ex:
        logger.exception(f"Error fetching simulation results {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            message="retrieving simulation data failed",
            details=ex.__str__(),
        ) from ex
