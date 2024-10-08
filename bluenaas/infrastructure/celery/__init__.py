from datetime import timedelta
import json
import time
from celery import Celery
from celery.worker.control import inspect_command
from loguru import logger
from typing import Any

from bluenaas.config.settings import settings
from bluenaas.core.stimulation.utils import is_current_varying_simulation
from bluenaas.core.stimulation.runners import (
    init_current_varying_simulation,
    init_frequency_varying_simulation,
)
from bluenaas.utils.cpu_usage import get_cpus_in_use
from bluenaas.domains.simulation import SingleNeuronSimulationConfig
from bluenaas.infrastructure.celery.bluenaas_task import BluenaasTask

celery_app = Celery(
    settings.CELERY_APP_NAME,
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    task_default_queue=settings.CELERY_QUE_SIMULATIONS,
    task_acks_late=True,
    task_send_sent_event=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_compression="gzip",
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    result_expires=timedelta(minutes=0.5),
    result_backend_transport_options={"global_keyprefix": "bnaas_sim_"},
    task_cls="bluenaas.infrastructure.celery.bluenaas_task:BluenaasTask",
)


@inspect_command()
def cpu_usage_stats(state):
    """
    Retrieves the current CPU usage statistics.

    This function utilizes the `get_cpus_in_use` method to obtain information about
    the CPUs currently in use.

    Args:
        state: The current state or context, provided by the inspecting command.

    Returns:
        dict: A dictionary containing CPU usage statistics, which may include:
            - cpus_in_use
            - total_cpus
            - cpu_usage_percent
    """
    return get_cpus_in_use()


# NOTE: test task
@celery_app.task(bind=True, queue="simulations")
def create_dummy_task(self):
    logger.info("[TASK_RECEIVED_NOW]")
    if self.request.hostname.startswith("worker0"):
        time.sleep(20)
    else:
        time.sleep(20)
    return "me"


@celery_app.task(bind=True, base=BluenaasTask)
def create_simulation(
    self,
    *,
    org_id: str,
    project_id: str,
    model_self: str,
    config: dict,
    token: str,
):
    """
    Creates a simulation based on the provided configuration and parameters.

    This task initializes either a current-varying or frequency-varying simulation
    depending on the configuration provided.

    Args:
        self: The current task instance (provided automatically by Celery).
        org_id (str): The ID of the organization initiating the simulation.
        project_id (str): The ID of the project under which the simulation is run.
        model_self (str): The identifier for the neuron model being simulated.
        config (dict): The configuration settings for the simulation, which must
                       be in a JSON-serializable format.
        token (str): Authorization token to access necessary resources for simulation.

    Returns:
        dict: A dictionary containing the simulation details:
            - org_id (str): The organization ID.
            - project_id (str): The project ID.
            - model_self (str): The model identifier.
            - config (dict): The original configuration used for the simulation.
            - result: The result of the simulation.
    """
    cf = SingleNeuronSimulationConfig(**json.loads(config))

    if is_current_varying_simulation(cf):
        result = init_current_varying_simulation(
            model_self,
            token,
            cf,
        )
    else:
        result = init_frequency_varying_simulation(
            model_self,
            token,
            cf,
        )
    return {
        "org_id": org_id,
        "project_id": project_id,
        "model_self": model_self,
        "config": config,
        "result": result,
    }


@celery_app.task(bind=True, base=BluenaasTask)
def create_background_simulation_task(
    self,
    *,
    org_id: str,
    project_id: str,
    model_self: str,
    config: dict,
    token: str,
    simulation_resource: dict[str, Any],
    track_status: bool,
):
    """
    Submits a simulation task (current varying or frequency varying) to the task queue.
    Updates the underlying nexus simulation based on the status of simulation as follows:

    - STARTED - When simulation task is picked up by a celery worker
    - SUCCESS - When simulation is finished and all data is received. The results are also stored in nexus resource
    - ERROR   - When there was an error in running simulation.

    Returns:
        dict: A dictionary containing the simulation details:
            - org_id (str): The organization ID.
            - project_id (str): The project ID.
            - model_self (str): The model identifier.
            - config (dict): The original configuration used for the simulation.
            - result: The result of the simulation.
    """
    sim_config = SingleNeuronSimulationConfig(**json.loads(config))

    if is_current_varying_simulation(sim_config):
        result = init_current_varying_simulation(
            model_self=model_self,
            token=token,
            config=sim_config,
            run_without_updates=True,
        )
    else:
        result = init_frequency_varying_simulation(
            model_self,
            token,
            sim_config,
        )
    return {
        "org_id": org_id,
        "project_id": project_id,
        "model_self": model_self,
        "config": config,
        "result": result,
    }
