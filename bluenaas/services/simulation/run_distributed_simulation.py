import json
from urllib.parse import quote_plus
from celery import states  # type: ignore
from loguru import logger
from http import HTTPStatus as status
from uuid import uuid4
import time
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.stimulation.utils import is_current_varying_simulation
from bluenaas.domains.nexus import FullNexusSimulationResource
from bluenaas.domains.simulation import (
    SimulationEvent,
    SingleNeuronSimulationConfig,
    SimulationStreamData,
    SimulationErrorMessage,
)
from bluenaas.services.simulation.constants import (
    task_state_descriptions,
    MESSAGE_WAIT_TIME_SECONDS,
    POLLING_INTERVAL_SECONDS,
)
from bluenaas.infrastructure.celery.tasks.single_simulation_runner import (
    single_simulation_runner,
)
from bluenaas.infrastructure.celery.tasks.initiate_simulation import initiate_simulation
from bluenaas.services.simulation.prepare_simulation_resource import (
    prepare_simulation_resources,
)
from bluenaas.utils.streaming import StreamingResponseWithCleanup, cleanup_worker
from bluenaas.utils.serializer import (
    deserialize_synapse_series_dict,
    serialize_synapse_series_list,
)
from bluenaas.utils.simulation import convert_to_simulation_response
from bluenaas.infrastructure.redis import redis_client


def get_event_from_task_state(state) -> SimulationEvent:
    """
    Get the event type based on the task state.
    """
    event: SimulationEvent = "info"
    if state in (states.PENDING, states.SUCCESS):
        event = "info"
    elif state == "PROGRESS":
        event = "data"
    elif state == states.FAILURE:
        event = "error"
    else:
        event = "info"

    return event


def build_stream_obj(task_result: SimulationStreamData, job_id: str):
    return f"{json.dumps(
            {
                "event": get_event_from_task_state(task_result['state']),
                "description": task_state_descriptions[task_result['state']],
                "state": task_result['state'].lower(),
                # TODO: Add task id
                # "task_id": task.id,
                "job_id": job_id,
                "data": task_result,
            }
        )}\n"


def build_stream_error(error_result: SimulationErrorMessage | None, job_id: str):
    error_details = (
        error_result["error"]
        if error_result is not None and "error" in error_result
        else "Unknown simulation error"
    )

    return f"{json.dumps(
        {
            "event": "error",
            "description": task_state_descriptions["FAILURE"],
            "state": "captured",
            "job_id": job_id, 
            "data": {                          
                "error_code": BlueNaasErrorCode.SIMULATION_ERROR,
                "message": "Simulation failed",
                "details": error_details
            }
        }
        )}\n"


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
        ) = prepare_simulation_resources(
            token,
            model_self,
            org_id,
            project_id,
            SingleNeuronSimulationConfig.model_validate(config),
            status="started",
        )

    try:
        # NOTE: build the model and calculate synapses series (current/frequency)
        # this should be ran before the sub simulation
        # Reason: to get the synapses series (it required to know how many parallel simulation should be run)
        # chaining tasks is not an option here using (chain from celery or "|")
        prep_job = initiate_simulation.apply_async(
            kwargs={
                "model_self": model_self,
                "token": token,
                "config": config.model_dump_json(),
            }
        )

        model_info = prep_job.get()
        # NOTE: used to calculate how many sub-simulation we should spin up
        (me_model_id, template_params, current_synapses, frequency_synapses) = (
            model_info
        )

        is_current_simulation = is_current_varying_simulation(config)
        resource_self = (
            simulation_resource["_self"] if simulation_resource is not None else None
        )

        channel_name = f"simulation_{uuid4()}"

        # TODO: better handling of this condition/loop to generate simulation tasks list
        if is_current_simulation:
            assert isinstance(amplitudes, list)
            for amplitude in amplitudes:
                for recording_location in config.record_from:
                    simulation_instances.append(
                        single_simulation_runner.s(
                            me_model_id=me_model_id,
                            synapses=current_synapses,
                            org_id=org_id,
                            project_id=project_id,
                            resource_self=resource_self,
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
                            channel_name=channel_name,
                        )
                    )

        else:
            synapses_by_frequency = deserialize_synapse_series_dict(frequency_synapses)
            for frequency in synapses_by_frequency:
                amplitudes = config.current_injection.stimulus.amplitudes

                # NOTE: frequency simulation should have only one amplitude (for the moment)
                # TODO: capture the assertion exception
                assert isinstance(amplitudes, float)

                for recording_location in config.record_from:
                    simulation_instances.append(
                        single_simulation_runner.s(
                            me_model_id=me_model_id,
                            synapses=serialize_synapse_series_list(
                                synapses_by_frequency[frequency]
                            ),
                            org_id=org_id,
                            project_id=project_id,
                            resource_self=resource_self,
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
                            channel_name=channel_name,
                        )
                    )

        grouped_tasks = group(simulation_instances)
        job = grouped_tasks.apply_async()

        # NOTE: if both `realtime` and `autosave` are enabled
        # the simulation will be streamed but the autosave will be handled in the celery task definition
        # please check: bluenaas/infrastructure/celery/single_simulation_task_class.py
        if realtime:
            pubsub = redis_client.pubsub()
            pubsub.subscribe(channel_name)

            def streamify():
                try:
                    # NOTE: first stream chunk is useful in different client to be able to get the job_id
                    # benefit: shutdown the simulation
                    yield f"{json.dumps(
                        {
                            "event": "init",
                            "description": task_state_descriptions["INIT"],
                            "state": "captured",
                            "job_id": job.id,
                            "resource_self": resource_self, 
                            "data": None,
                        }
                    )}\n"

                    # successful_message_count might not always be equal to the count of celery tasks that have successfully finished
                    # because there might be a time difference between when we receive the successful message from redis queue and when celery succesfully registers
                    # the task as complete.
                    successful_message_count = 0

                    while True:
                        message = pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=MESSAGE_WAIT_TIME_SECONDS,
                        )
                        if job.failed():
                            logger.debug(
                                f"Job {job.id} failed without publishing result for {MESSAGE_WAIT_TIME_SECONDS} seconds"
                            )
                            yield build_stream_error(None, job.id)
                            break

                        if message is not None:
                            message_data = json.loads(message["data"])

                            if message_data["state"] == "SUCCESS":
                                successful_message_count = successful_message_count + 1
                                logger.debug(
                                    f"Received {successful_message_count} shutdown events for {job.id}"
                                )
                                if successful_message_count == len(
                                    simulation_instances
                                ):
                                    logger.debug(f"Received all results for {job.id}")
                                    break

                            elif message_data["state"] == "FAILURE":
                                logger.debug(
                                    f"Received failure message for job {job.id} {message_data}"
                                )
                                yield build_stream_error(message_data, job.id)
                                break

                            else:
                                yield build_stream_obj(message_data, job.id)
                        time.sleep(
                            POLLING_INTERVAL_SECONDS
                        )  # Do not continuously poll the queue to allow server to attend to other tasks.

                    status = None
                    if successful_message_count == len(simulation_instances):
                        logger.debug("JOB SUCCESSFUL")
                        status = states.SUCCESS
                    elif (
                        successful_message_count < len(simulation_instances)
                        and successful_message_count > 0
                    ):
                        # NOTE: this is new state introduced if we want to be more precise about the quality of the results
                        logger.debug(
                            f"Job partially successful. {successful_message_count} / {len(simulation_instances)} completed"
                        )
                        status = "PARTIAL_SUCCESS"
                    else:
                        logger.debug(
                            f"JOB FAILED. Completed Tasks {successful_message_count}"
                        )
                        status = states.FAILURE

                    # TODO: check for the revoked task status
                    description = task_state_descriptions[status]

                    # finally stream the latest status of the simulation
                    yield f"{json.dumps(
                        {
                            "event": "info",
                            "description":description,
                            "state": status,
                            "job_id": job.id,
                            "resource_self": resource_self, 
                            "data": None,
                        }
                    )}\n"

                except Exception as ex:
                    logger.info(f"Exception in task streaming: {ex}")
                    raise Exception("Trouble while streaming simulation data")
                finally:
                    logger.exception(f"Closing channel {channel_name}")
                    pubsub.unsubscribe(channel_name)
                    pubsub.close()

            return StreamingResponseWithCleanup(
                streamify(),
                finalizer=lambda: cleanup_worker(
                    job.id,
                ),
                media_type="application/octet-stream",
                headers={
                    "x-bnaas-job": job.id,
                },
            )

        elif autosave:
            # NOTE: if autosave simulation is enabled then return the simulation with
            # 1- job_id to be able to shutdown the simulation
            # 2- query nexus for the simulation (status and result) at any time
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
        logger.exception(f"Error while running simulation {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="Error while running simulation",
            details=ex.__str__(),
        ) from ex
