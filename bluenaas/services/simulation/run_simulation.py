import json
from celery import states
from loguru import logger
from celery.exceptions import TaskRevokedError

from bluenaas.domains.simulation import SingleNeuronSimulationConfig
from bluenaas.utils.streaming import StreamingResponseWithCleanup, cleanup_worker

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


def run_simulation(
    token: str,
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
):
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

    task = create_simulation.apply_async(
        kwargs={
            "model_self": model_self,
            "org_id": org_id,
            "project_id": project_id,
            "config": config.model_dump_json(),
            "token": token,
        },
        ignore_result=True,
    )
    logger.info(f"@@task id {task.id}")
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
                    "event": "info",
                    "task_id": task.id,
                }
            )}\n"

            while not task_result.ready():
                if isinstance(task.info, TaskRevokedError):
                    yield f"{json.dumps(
                        {
                            "type":  get_event_from_task_state(task.state),
                            "description": task_state_descriptions[task.state],
                            "state": task.state.lower(),
                            "data": None,
                        }
                    )}\n"
                    break

                yield f"{json.dumps(
                        {
                            "type":  get_event_from_task_state(task.state),
                            "description": task_state_descriptions[task.state],
                            "state": task.state.lower(),
                            "data": task.info,
                        }
                    )}\n"
        except Exception as ex:
            logger.info(f"Exception in task streaming: {ex}")
            # TODO: better way to terminate the task
            celery_app.control.revoke(task.id, terminate=True)
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
