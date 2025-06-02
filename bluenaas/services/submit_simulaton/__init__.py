from fastapi import BackgroundTasks
from loguru import logger
from rq import Queue

from bluenaas.domains.nexus import FullNexusSimulationResource
from bluenaas.domains.simulation import SingleNeuronSimulationConfig
from bluenaas.services.submit_simulaton.setup_resources import (
    setup_simulation_resources,
)
from bluenaas.utils.simulation import convert_to_simulation_response
from bluenaas.services.single_neuron_simulation import execute_single_neuron_simulation


def submit_background_simulation(
    job_queue: Queue,
    org_id: str,
    project_id: str,
    model_self: str,
    config: SingleNeuronSimulationConfig,
    token: str,
):
    (
        me_model_self,
        synaptome_model_self,
        _stimulus_plot_data,
        sim_response,
        simulation_resource,
    ) = setup_simulation_resources(
        token,
        model_self,
        org_id,
        project_id,
        config,
    )

    logger.debug(
        f"Submitting simulation task for resource {simulation_resource["_self"]}"
    )
    # Step 2: Add background task to process simulation
    job_queue.enqueue(
        execute_single_neuron_simulation,
        kwargs={
            "org_id": org_id,
            "project_id": project_id,
            "model_id": model_self,
            "token": token,
            "config": config,
            "realtime": False,
            "simulation_resource_self": sim_response["_self"],
        },
    )
    # background_tasks.add_task(
    #     execute_single_neuron_simulation,
    #     org_id=org_id,
    #     project_id=project_id,
    #     model_id=model_self,
    #     token=token,
    #     config=config,
    #     # req_id=request_id,
    #     realtime=False,
    #     simulation_resource_self=sim_response["_self"],
    # )

    # Step 3: Return simulation status to user
    return convert_to_simulation_response(
        simulation_uri=simulation_resource["@id"],
        simulation_resource=FullNexusSimulationResource.model_validate(
            simulation_resource,
        ),
        me_model_self=me_model_self,
        synaptome_model_self=synaptome_model_self,
        simulation_config=config,
        results=None,
    )
