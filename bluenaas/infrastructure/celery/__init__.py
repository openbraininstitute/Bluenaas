from datetime import timedelta
import json
import time
from celery import Celery
from celery.worker.control import inspect_command
from loguru import logger
from typing import Any, Optional

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
    result_extended=True,
    task_send_sent_event=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_compression="gzip",
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    # result_expires=timedelta(minutes=0.5),
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


@celery_app.task(
    bind=True,
    base=BluenaasTask,
    serializer="json",
)
def create_simulation(
    self,
    *,
    org_id: str,
    project_id: str,
    model_self: str,
    config: dict,
    token: str,
    simulation_resource: Optional[dict[str, Any]] = None,
    stimulus_plot_data: Optional[list[dict[str, Any]]] = None,
    enable_realtime: bool = True,
    autosave: bool = False,
):
    """
    Creates a simulation based on the provided configuration and parameters.

    This task initializes a simulation using the provided configuration, which can either
    be current-varying or frequency-varying, depending on the setup.

    Args:
        self: The current task instance (automatically provided by Celery).
        org_id (str): The ID of the organization initiating the simulation.
        project_id (str): The ID of the project under which the simulation is executed.
        model_self (str): The identifier for the neuron model being simulated.
        config (dict): The configuration settings for the simulation, provided in a
                       JSON-serializable format.
        token (str): The authorization token used to authenticate and access necessary
                     resources for the simulation.
        simulation_resource (Optional[dict[str, Any]]): An optional resource object
                     that may contain additional data required for the simulation. Defaults to None.
        stimulus_plot_data (Optional[list[dict[str, Any]]]): Optional data for stimulus
                     plotting during the simulation. Defaults to None.
        enable_realtime (bool): Whether to enable real-time updates during the simulation.
                     Defaults to True.
        autosave (bool): Whether the simulation should be automatically saved after completion.
                     Defaults to False.

    Returns:
        dict: A dictionary containing the details of the created simulation, including:
            - org_id (str): The organization ID.
            - project_id (str): The project ID.
            - model_self (str): The neuron model identifier used in the simulation.
            - config (dict): The configuration settings used for the simulation.
            - result: The result of the simulation.
    """
    cf = SingleNeuronSimulationConfig(**json.loads(config))

    if is_current_varying_simulation(cf):
        result = init_current_varying_simulation(
            model_self,
            token,
            cf,
            enable_realtime=enable_realtime,
        )
    else:
        result = init_frequency_varying_simulation(
            model_self,
            token,
            cf,
            enable_realtime=enable_realtime,
        )

    return {
        "org_id": org_id,
        "project_id": project_id,
        "model_self": model_self,
        "config": config,
        "result": result,
        "simulation_resource": simulation_resource,
        "stimulus_plot_data": stimulus_plot_data,
    }
