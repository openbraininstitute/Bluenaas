from celery import states
from loguru import logger
from http import HTTPStatus

from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    SimulationStatusResponse,
)
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    SimulationError,
)
from urllib.parse import quote_plus


def submit_simulation(
    token: str,
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
):
    """
    Starts a (background) simulation job in celery and returns simulation status right away, without waiting for simulation to finish.

    Args:
        token (str): Authorization token to access the simulation.
        model_self (str): The _self of the neuron model to simulate.
        org_id (str): The ID of the organization running the simulation.
        project_id (str): The ID of the project the simulation belongs to.
        config (SingleNeuronSimulationConfig): The simulation configuration.

    Returns:
        SimulationResult
    """
    from bluenaas.infrastructure.celery import (
        create_simulation,
    )

    # Step 1: Create nexus resource for simulation and use status "PENDING"
    try:
        nexus_helper = Nexus({"token": token, "model_self_url": model_self})
        simulation_resource = nexus_helper.create_simulation_resource(
            simulation_config=config,
            stimulus=None,
            status=states.PENDING,
            lab_id=org_id,
            project_id=project_id,
        )
        logger.debug(
            f"Created nexus resource for simulation {simulation_resource["@id"]}"
        )
    except SimulationError as ex:
        logger.debug(f"Creating nexus resource for simulation failed {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            message="Creating nexus resource for simulation failed",
            details=ex.__str__(),
        ) from ex
    except Exception as ex:
        logger.exception(f"Creating nexus resource for simulation failed {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.SIMULATION_ERROR,
            message="Creating nexus resource for simulation failed",
            details=ex.__str__(),
        ) from ex

    # Step 2: Submit task to celery
    task = create_simulation.apply_async(
        kwargs={
            "org_id": org_id,
            "project_id": project_id,
            "model_self": model_self,
            "config": config.model_dump_json(),
            "token": token,
            "simulation_resource": simulation_resource,
            "enable_realtime": False,
        },
    )
    logger.debug(f"Task submitted with id {task.id}")

    # Step 3: Return simulation status to user
    return SimulationStatusResponse(
        id=quote_plus(simulation_resource["@id"]), status="PENDING", results=None
    )
