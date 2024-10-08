from http import HTTPStatus
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.domains.simulation import SimulationStatus
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
)


def fetch_simulation_status_and_results(
    token: str, org_id: str, project_id: str, simulation_id: str
) -> SimulationStatus:
    try:
        nexus_helper = Nexus(
            {"token": token, "model_self_url": simulation_id}
        )  # TODO: Remove model_id as a required field for nexus helper
        simulation_resource = nexus_helper.fetch_resource_for_org_project(
            org_label=org_id, project_label=project_id, resource_id=simulation_id
        )
        return SimulationStatus(
            id=simulation_id, status=simulation_resource["status"], results=None
        )
    except Exception as ex:
        raise BlueNaasError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            message="retrieving simulation data failed",
            details=ex.__str__(),
        ) from ex
