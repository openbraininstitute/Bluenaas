from http import HTTPStatus

from pydantic import Field
from bluenaas.external.nexus.nexus import Nexus
from urllib.parse import unquote
from loguru import logger
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode


def deprecate_simulation(
    token: str,
    org_id: str,
    project_id: str,
    simulation_uri: str = Field(..., description="URL-encoded simulation URI"),
) -> None:
    try:
        simulation_id = unquote(simulation_uri)
        nexus_helper = Nexus(
            {"token": token, "model_self_url": ""}
        )  # TODO: Remove model_id as a required field for nexus helper

        simulation_resource = nexus_helper.fetch_resource_for_org_project(
            org_label=org_id,
            project_label=project_id,
            resource_id=simulation_id,
        )
        nexus_helper.deprecate_resource(
            org_label=org_id,
            project_label=project_id,
            resource_id=simulation_id,
            previous_rev=simulation_resource["_rev"],
        )
    except Exception as ex:
        logger.exception(f"Error fetching simulation results {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            message="retrieving simulation data failed",
            details=ex.__str__(),
        ) from ex
