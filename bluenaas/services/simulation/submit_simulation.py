from celery import states
from loguru import logger
from http import HTTPStatus

from bluenaas.domains.simulation import SingleNeuronSimulationConfig, SimulationStatus
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    SimulationError,
)

task_state_descriptions = {
    states.PENDING: "Simulation is waiting for execution.",
    states.STARTED: "Simulation has started executing.",
    states.SUCCESS: "The simulation completed successfully.",
    states.FAILURE: "The simulation has failed.",
    states.REVOKED: "The simulation has been canceled.",
    "PROGRESS": "Simulation is currently in progress.",
}


def get_event_from_task_state(state):
    """
    Get the event type based on the task state.
    """
    if state in (states.PENDING, states.SUCCESS):
        event = "info"
    elif state == "PROGRESS":
        event = "data"
    elif state == states.FAILURE:
        event = "error"
    else:
        event = "info"  # Default to info for unrecognized states

    return event.lower()


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
        create_background_simulation_task,
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
    task = create_background_simulation_task.apply_async(
        kwargs={
            "org_id": org_id,
            "project_id": project_id,
            "model_self": model_self,
            "config": config.model_dump_json(),
            "token": token,
            "simulation_resource": simulation_resource,
            "track_status": True,
        },
    )
    logger.debug(f"Task submitted with id {task.id}")

    # Step 3: Return simulation status to user
    return SimulationStatus(
        id=simulation_resource["@id"], status=states.PENDING, results=None
    )
