from celery import states
from loguru import logger
from http import HTTPStatus
import json
from urllib.parse import quote_plus

from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    StimulationPlotConfig,
    SimulationStimulusConfig,
    StimulationItemResponse,
)
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    SimulationError,
)
from bluenaas.core.model import model_factory
from bluenaas.utils.simulation import to_simulation_response


def get_stimulation_plot_data(
    token: str, me_model_self: str, stimulus: SimulationStimulusConfig
) -> list[StimulationItemResponse]:
    model = model_factory(
        model_self=me_model_self,
        hyamp=None,
        bearer_token=token,
    )
    stimulus_config = StimulationPlotConfig(
        stimulusProtocol=stimulus.stimulusProtocol,
        amplitudes=stimulus.amplitudes
        if isinstance(stimulus.amplitudes, list)
        else [stimulus.amplitudes],
    )
    stimulus_factory_plot = StimulusFactoryPlot(
        stimulus_config,
        model.threshold_current,
    )
    plot_data = stimulus_factory_plot.apply_stim()
    for trace in plot_data:
        StimulationItemResponse.model_validate(trace)
    return plot_data


def submit_simulation(
    token: str,
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
):
    """
    Starts a (background) simulation job in celery and returns simulation status right away, without waiting for the simulation to finish.

    Args:
        token (str): Authorization token to access the simulation.
        model_self (str): The _self of the neuron model to simulate.
        org_id (str): The ID of the organization running the simulation.
        project_id (str): The ID of the project the simulation belongs to.
        config (SingleNeuronSimulationConfig): The simulation configuration.

    Returns:
        SimulationStatusResponse
    """
    from bluenaas.infrastructure.celery import (
        create_simulation,
    )

    nexus_helper = Nexus({"token": token, "model_self_url": model_self})

    # Step 1: Generate stimulus data to be saved in nexus resource in step 1
    try:
        me_model_self = model_self
        synaptome_model_self = None
        if config.type == "synaptome-simulation":
            synaptome_model_self = model_self
            synaptome_model = nexus_helper.fetch_resource_by_self(synaptome_model_self)
            me_model_id = synaptome_model["used"]["@id"]
            me_model = nexus_helper.fetch_resource_by_id(me_model_id)
            me_model_self = me_model["_self"]

        stimulus_plot_data = get_stimulation_plot_data(
            token=token,
            me_model_self=me_model_self,
            stimulus=config.currentInjection.stimulus,
        )
    except Exception as ex:
        logger.exception(f"Generation of stimulus data failed {ex}")
        raise BlueNaasError(
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.SIMULATION_ERROR,
            message="Generation of stimulus data failed",
            details=ex.__str__(),
        )

    # Step 2: Create nexus resource for simulation and use status "PENDING"
    try:
        sim_response = nexus_helper.create_simulation_resource(
            simulation_config=config,
            status=states.PENDING,
            lab_id=org_id,
            project_id=project_id,
        )
        simulation_resource = nexus_helper.fetch_resource_for_org_project(
            org_label=org_id,
            project_label=project_id,
            resource_id=sim_response["@id"],
        )
    except SimulationError as ex:
        logger.exception(f"Creating nexus resource for simulation failed {ex}")
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
            "stimulus_plot_data": json.dumps(stimulus_plot_data),
            "token": token,
            "simulation_resource": sim_response,
            "enable_realtime": False,
        },
    )
    logger.debug(f"Task submitted with id {task.id}")

    # Step 3: Return simulation status to user
    return to_simulation_response(
        encoded_simulation_id=quote_plus(simulation_resource["@id"]),
        simulation_resource=simulation_resource,
        me_model_self=me_model_self,
        synaptome_model_self=synaptome_model_self,
        distribution=None,
    )
