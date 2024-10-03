import json
from loguru import logger
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
)
from celery.signals import before_task_publish, after_task_publish, worker_ready
from bluenaas.infrastructure.celery import celery_app

worker_registry = {}


def get_available_workers():
    # Get a list of available workers
    workers = celery_app.control.inspect().active()
    return workers


def get_workers_stats(worker_id):
    # Get the current CPU usage of a worker
    workers = celery_app.control.inspect().stats()
    return workers


def start_new_worker(cpus):
    # Spin up a new worker with the required number of CPUs
    # This can be done using a cloud provider's API or a container orchestration tool
    # For demonstration purposes, we'll just print a message
    print(f"Spinning up new worker with {cpus} CPUs")
    return f"worker-{cpus}"


def scale_workers(simulation_cpus):
    # Check if a worker has enough CPUs to run the simulation
    for worker_id, worker in worker_registry.items():
        if worker["available_cpus"] >= simulation_cpus:
            return worker_id

    # If no worker has enough CPUs, spin up a new worker
    new_worker_id = start_new_worker(simulation_cpus)
    worker_registry[new_worker_id] = {"available_cpus": simulation_cpus}
    return new_worker_id


@worker_ready.connect
def worker_connect(sender, *args, **kwargs):
    logger.info(f"args --> {args=}")
    logger.info(f"sender --> {sender=}")
    logger.info(f"kwargs --> {kwargs=}")
    pass


@before_task_publish.connect
def before_task(
    body, exchange, routing_key, headers, properties, declare, retry_policy, **kwargs
):
    logger.info("@@before_task_publish")
    logger.info(f"@@config, {body[1]["config"]} {type(body[1]["config"])}")
    _config = SingleNeuronSimulationConfig.model_validate(json.loads(body[1]["config"]))
    cpu_needed = len(_config.currentInjection.stimulus.amplitudes)
    logger.info(f"@@__cpu_needed__: {cpu_needed}")
    logger.info(f"@@__all_stats__: {celery_app.control.inspect().stats()}")
    logger.info(f"@@__all_stats__: {celery_app.control.inspect().active()}")
    logger.info("@@")
    pass


@after_task_publish.connect
def after_task(headers, body, exchange, routing_key, **kwargs):
    logger.info("@@after_task_publish")
    # logger.info(f"@@body, {body}")
    logger.info("@@")
    pass
