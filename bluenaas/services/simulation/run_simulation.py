import json
from celery import states
from loguru import logger
from celery.exceptions import TaskRevokedError

from bluenaas.core.exceptions import ChildSimulationError, SimulationError
from bluenaas.domains.simulation import (
    SimulationEvent,
    SingleNeuronSimulationConfig,
    StreamSimulationResponse,
)
from bluenaas.services.simulation.submit_simulation.prepare_resources import (
    prepare_simulation_resources,
)
from bluenaas.utils.streaming import StreamingResponseWithCleanup, cleanup_worker

task_state_descriptions = {
    states.PENDING: "Simulation is waiting for execution.",
    states.STARTED: "Simulation has started executing.",
    states.SUCCESS: "The simulation completed successfully.",
    states.FAILURE: "The simulation has failed.",
    states.REVOKED: "The simulation has been canceled.",
    "PROGRESS": "Simulation is currently in progress.",
    "INIT": "Simulation is captured by the system",
}


def get_event_from_task_state(state) -> SimulationEvent:
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


def run_simulation(
    token: str,
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    autosave: bool = False,
) -> StreamSimulationResponse:
    """
    Initiates a simulation task and streams real-time updates to the client.

    Args:
        token (str): Authorization token to access the simulation.
        model_self (str): The _self of the neuron model to simulate.
        org_id (str): The ID of the organization running the simulation.
        project_id (str): The ID of the project the simulation belongs to.
        config (SingleNeuronSimulationConfig): The simulation configuration.

    Returns:
        StreamingResponse: A stream of task updates, including the task ID and status changes.
    """
    from bluenaas.infrastructure.celery import create_simulation, celery_app
    from celery.result import AsyncResult

    if autosave:
        (
            _,
            _,
            stimulus_plot_data,
            sim_response,
            _,
        ) = prepare_simulation_resources(
            token,
            model_self,
            org_id,
            project_id,
            SingleNeuronSimulationConfig.model_validate(config),
        )

    task = create_simulation.apply_async(
        kwargs={
            "model_self": model_self,
            "org_id": org_id,
            "project_id": project_id,
            "config": config.model_dump_json(),
            "token": token,
            "simulation_resource": sim_response,
            "stimulus_plot_data": json.dumps(stimulus_plot_data),
            "autosave": autosave,
        },
        ignore_result=True,
    )

    task_result = AsyncResult(
        task.id,
        app=celery_app,
    )

    def streamify():
        """
        A generator that streams simulation updates to the client.

        Yields:
            str: A JSON-encoded message containing simulation info and status updates.
        """
        try:
            yield f"{json.dumps(
                {
                    "event": "init",
                    "description": task_state_descriptions["INIT"],
                    "state": "captured",
                    "task_id": task.id,
                    "data": None,
                }
            )}\n"

            while not task_result.ready():
                if (
                    isinstance(task.info, TaskRevokedError)
                    or isinstance(task.info, SimulationError)
                    or isinstance(task.info, ChildSimulationError)
                ):
                    yield f"{json.dumps(
                        {
                            "event":  get_event_from_task_state(task.state),
                            "description": task_state_descriptions[task.state],
                            "state": task.state.lower(),
                            "data": None,
                            "task_id": task.id,
                        }
                    )}\n"
                    break

                yield f"{json.dumps(
                        {
                            "event":  get_event_from_task_state(task.state),
                            "description": task_state_descriptions[task.state],
                            "state": task.state.lower(),
                            "data": task.info,
                            "task_id": task.id,
                        }
                    )}\n"

        except Exception as ex:
            logger.info(f"Exception in task streaming: {ex}")
            raise Exception("Trouble while streaming simulation data")

    return StreamingResponseWithCleanup(
        streamify(),
        finalizer=lambda: cleanup_worker(
            task.id,
        ),
        media_type="application/octet-stream",
        headers={
            "x-bnaas-task": task.id,
        },
    )
