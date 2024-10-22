import json
from multiprocessing.pool import AsyncResult
from urllib.parse import quote_plus

from loguru import logger
from bluenaas.core.stimulation.utils import is_current_varying_simulation
from bluenaas.domains.nexus import FullNexusSimulationResource
from bluenaas.domains.simulation import (
    SimulationEvent,
    SingleNeuronSimulationConfig,
)
from bluenaas.infrastructure.celery.tasks.single_simulation_runner import (
    single_simulation_runner,
)
from bluenaas.infrastructure.celery.tasks.initiate_simulation import initiate_simulation
from bluenaas.services.simulation.submit_simulation.setup_resources import (
    setup_simulation_resources,
)
from bluenaas.utils.serializer import deserialize_synapse_series_dict
from bluenaas.utils.simulation import convert_to_simulation_response
from celery import states

from bluenaas.utils.streaming import StreamingResponseWithCleanup, cleanup_worker


task_state_descriptions = {
    "INIT": "Simulation is captured by the system",
    "PROGRESS": "Simulation is currently in progress.",
    "PENDING": "Simulation is waiting for execution.",
    "STARTED": "Simulation has started executing.",
    "SUCCESS": "The simulation completed successfully.",
    "FAILURE": "The simulation has failed.",
    "REVOKED": "The simulation has been canceled.",
    "PARTIAL_SUCCESS": "The simulation has been completed but not fully successful.",
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
        event = "info"

    return event.lower()


def build_stream_obj(task: AsyncResult, job_id: str):
    res = f"{json.dumps(
            {
                "event": get_event_from_task_state(task.state),
                "description": task_state_descriptions[task.state],
                "state": task.state.lower(),
                "task_id": task.id,
                "job_id": job_id,
                "data": task.result or None,
            }
        )}\n"
    return res


def run_distributed_simulation(
    org_id: str,
    project_id: str,
    model_self: str,
    token: str,
    config: SingleNeuronSimulationConfig,
    autosave: bool = False,
    realtime: bool = False,
):
    from celery import group

    amplitudes = config.current_injection.stimulus.amplitudes
    simulation_instances = []
    simulation_resource = None

    if autosave:
        (
            me_model_self,
            synaptome_model_self,
            _,
            _,
            simulation_resource,
        ) = setup_simulation_resources(
            token,
            model_self,
            org_id,
            project_id,
            SingleNeuronSimulationConfig.model_validate(config),
            status="started",
        )

    try:
        prep_job = initiate_simulation.apply_async(
            kwargs={
                "model_self": model_self,
                "token": token,
                "config": config.model_dump_json(),
            }
        )
        logger.info(f"@@-------- {prep_job.id} --------")
        output = prep_job.get()
        (_, _, _, frequency_to_synapse_config) = output

        is_current_simulation = is_current_varying_simulation(config)
        resource_self = (
            simulation_resource["_self"] if simulation_resource is not None else None
        )
        logger.info(f"@@-------- {is_current_simulation=} --------")
        if is_current_simulation:
            for amplitude in amplitudes:
                for recording_location in config.record_from:
                    simulation_instances.append(
                        single_simulation_runner.s(
                            output,
                            org_id=org_id,
                            project_id=project_id,
                            simulation_resource_self=resource_self,
                            token=token,
                            config=config.model_dump_json(),
                            amplitude=amplitude,
                            frequency=None,
                            recording_location=recording_location.model_dump_json(),
                            injection_segment=0.5,
                            thres_perc=None,
                            add_hypamp=True,
                            realtime=realtime,
                            autosave=autosave,
                        )
                    )

        else:
            for frequency in deserialize_synapse_series_dict(
                frequency_to_synapse_config
            ):
                amplitudes = config.current_injection.stimulus.amplitudes

                # NOTE: frequency simulation should have only one amplitude (for the moment)
                assert isinstance(amplitudes, float)

                for recording_location in config.record_from:
                    simulation_instances.append(
                        single_simulation_runner.s(
                            output,
                            org_id=org_id,
                            project_id=project_id,
                            simulation_resource_self=resource_self,
                            token=token,
                            config=config.model_dump_json(),
                            amplitude=amplitudes,
                            frequency=frequency,
                            recording_location=recording_location.model_dump_json(),
                            injection_segment=0.5,
                            thres_perc=None,
                            add_hypamp=True,
                            realtime=realtime,
                            autosave=autosave,
                        )
                    )

        logger.info(f"@@-------- {simulation_instances=} --------")
        job = group(simulation_instances)
        tasks = job.apply_async()
        logger.info(f"@@-------- {tasks.id} --------")
        logger.info(f"@@-------- {tasks.results} --------")
        logger.info(f"@@-------- {realtime=} --------")
        if realtime:
            logger.info("@@-------- inside --------")

            def streamify():
                try:
                    logger.info("@@-------- yielding --------")
                    yield f"{json.dumps(
                        {
                            "event": "init",
                            "description": task_state_descriptions["INIT"],
                            "state": "captured",
                            "job_id": tasks.id,
                            "resource_self": resource_self, 
                            "data": None,
                        }
                    )}\n"

                    while not tasks.ready():
                        for v in tasks.results:
                            logger.info(f"@@->{v.status=}/{v.info=}")
                            yield build_stream_obj(v, tasks.id)

                    status = None
                    if tasks.successful():
                        status = states.SUCCESS
                    elif tasks.completed_count() > 0 and tasks.completed_count() < len(
                        tasks.results
                    ):
                        status = "PARTIAL_SUCCESS"
                    else:
                        status = states.FAILURE
                    # TODO: check for the revoked task status
                    description = task_state_descriptions[status]

                    yield f"{json.dumps(
                        {
                            "event": "info",
                            "description":description,
                            "state": status,
                            "job_id": tasks.id,
                            "resource_self": resource_self, 
                            "data": None,
                        }
                    )}\n"

                except Exception as ex:
                    logger.info(f"Exception in task streaming: {ex}")
                    raise Exception("Trouble while streaming simulation data")

            return StreamingResponseWithCleanup(
                streamify(),
                finalizer=lambda: cleanup_worker(
                    tasks.id,
                ),
                media_type="application/octet-stream",
                headers={
                    "x-bnaas-task": tasks.id,
                },
            )

        elif autosave:
            return convert_to_simulation_response(
                job_id=job.id,
                simulation_uri=quote_plus(simulation_resource["@id"]),
                simulation_resource=FullNexusSimulationResource.model_validate(
                    simulation_resource,
                ),
                me_model_self=me_model_self,
                synaptome_model_self=synaptome_model_self,
                distribution=None,
            )

    except Exception as ex:
        logger.exception(f"error: {ex=}")
