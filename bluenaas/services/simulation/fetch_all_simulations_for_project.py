from http import HTTPStatus
from typing import Optional
from bluenaas.external.nexus.nexus import Nexus
from urllib.parse import quote_plus
from bluenaas.domains.simulation import (
    SimulationStatusResponse,
    SimulationType,
    NexusSimulationType,
    PaginatedSimulations,
)
from loguru import logger
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.utils.simulation import (
    to_simulation_response,
    get_nexus_simulation_type,
    get_simulation_type,
)


def fetch_all_simulations_of_project(
    token: str,
    org_id: str,
    project_id: str,
    sim_type: Optional[SimulationType],
    offset: int,
    size: int,
) -> PaginatedSimulations:
    try:
        nexus_sim_types: list[NexusSimulationType] = (
            ["SingleNeuronSimulation", "SynaptomeSimulation"]
            if sim_type is None
            else [get_nexus_simulation_type(sim_type)]
        )

        nexus_helper = Nexus(
            {"token": token, "model_self_url": ""}
        )  # TODO: Remove model_id as a required field for nexus helper

        nexus_sim_reponse = nexus_helper.fetch_resources_of_type(
            org_label=org_id,
            project_label=project_id,
            res_types=nexus_sim_types,
            offset=offset,
            size=size,
        )
        nexus_simulations = nexus_sim_reponse["_results"]

        simulations: list[SimulationStatusResponse] = []

        for nexus_sim in nexus_simulations:
            try:
                # nexus_sim does not include all information that we need, specifically `used`. So we need to fetch full resource
                full_simulation_resource = nexus_helper.fetch_resource_for_org_project(
                    org_label=org_id,
                    project_label=project_id,
                    resource_id=nexus_sim["@id"],
                )
                used_model_id = full_simulation_resource["used"]["@id"]
                sim_type = get_simulation_type(
                    simulation_resource=full_simulation_resource
                )

                if sim_type == "single-neuron-simulation":
                    me_model_self = nexus_helper.fetch_resource_for_org_project(
                        org_label=org_id,
                        project_label=project_id,
                        resource_id=used_model_id,
                    )["_self"]
                    synaptome_model_self = None
                else:
                    synaptome_model = nexus_helper.fetch_resource_for_org_project(
                        org_label=org_id,
                        project_label=project_id,
                        resource_id=used_model_id,
                    )
                    synaptome_model_self = synaptome_model["_self"]
                    me_model = nexus_helper.fetch_resource_for_org_project(
                        org_label=org_id,
                        project_label=project_id,
                        resource_id=synaptome_model["used"]["@id"],
                    )
                    me_model_self = me_model["_self"]

                simulation = to_simulation_response(
                    encoded_simulation_id=quote_plus(full_simulation_resource["@id"]),
                    simulation_resource=full_simulation_resource,
                    me_model_self=me_model_self,
                    synaptome_model_self=synaptome_model_self,
                    distribution=None,
                )
                simulations.append(simulation)
            except Exception as err:
                logger.warning(
                    f"Nexus Simulation {nexus_sim["_self"]} could not be converted to a bluenaas compatible simulation {err}"
                )

        return PaginatedSimulations(
            page_offset=offset,
            page_size=len(simulations),
            total=nexus_sim_reponse["_total"],
            results=simulations,
        )
    except Exception as ex:
        logger.exception(f"Error fetching simulations in project {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            message="retrieving simulation data failed",
            details=ex.__str__(),
        ) from ex
