"""
Simulation Routes
contains the single neuron simulation endpoint (single neuron, single neuron with synaptome)
"""

from datetime import datetime
import time
from fastapi import APIRouter, Depends, Path, Query, Response, status
from typing import Optional


from bluenaas.config.settings import settings
from bluenaas.domains.nexus import DeprecateNexusResponse
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    SimulationResultItemResponse,
    SimulationType,
    PaginatedSimulationsResponse,
    StreamSimulationBodyRequest,
    StreamSimulationResponse,
)
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.infrastructure.celery import create_dummy_task
from bluenaas.services.simulation.run_simulation import run_simulation
from bluenaas.services.simulation.stop_simulation import stop_simulation
from bluenaas.services.simulation.submit_simulation import submit_simulation
from bluenaas.core.exceptions import BlueNaasError
from bluenaas.services.simulation.fetch_simulation_status_and_results import (
    fetch_simulation_status_and_results,
)
from bluenaas.services.simulation.deprecate_simulation import deprecate_simulation
from bluenaas.services.simulation.fetch_all_simulations_for_project import (
    fetch_all_simulations_of_project,
)

router = APIRouter(
    prefix="/simulation",
    tags=["Simulation"],
)


@router.post(
    "/single-neuron/dummy",
    include_in_schema=settings.DEPLOYMENT_ENV != "production",
)
def dummy_simulation(
    tasks: int = Query(min=10, default=20),
):
    for i in range(tasks):
        create_dummy_task.apply_async()
        time.sleep(1)
        i += 1


@router.post(
    "/single-neuron/{org_id}/{project_id}/run-realtime",
    summary="Initiates a simulation for a single neuron or synaptome model and returns a simulation results in realtime.",
)
def execute_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    request: StreamSimulationBodyRequest,
    token: str = Depends(verify_jwt),
) -> StreamSimulationResponse:
    """
    This endpoint starts the simulation process and allows for real-time updates of
    the simulation's progress. The response includes immediate details about the simulation
    task, enabling clients to track the status as it runs.

    Args:

        model_self (str):
            The unique identifier for the neuron model to be simulated.
            The model's designated self within nexus's context.

        org_id (str):
            The organization ID associated with the simulation request. This helps in scoping
            the simulation to the appropriate organizational context.

        project_id (str):
            The project ID associated with the simulation request. This ID organizes the simulation
            within a specific project framework.

        request (StreamSimulationBodyRequest):
            The body of the request containing the necessary parameters to configure the simulation:
                - **config** (SingleNeuronSimulationConfig): The configuration settings required for the simulation.
                - **autosave** (Optional[bool]): A boolean flag indicating whether the simulation results should
                  be saved automatically during the execution. Defaults to `False`.

    Returns:

        StreamSimulationResponse:
            A structured response containing:
                - **task_id** (str): The unique identifier for the initiated simulation task.
                - **status** (str): The current status of the simulation (e.g., "running").
                - **message** (str): An informative message regarding the initiation of the simulation.
                - **data** (SimulationSteamData): the trace data for a specific recording

    Raises:

        HTTPException:
            An HTTP exception may be raised if there are issues with the simulation request, such
            as invalid parameters or lack of authorization.

    Notes:

        This endpoint is designed for real-time simulation execution. Ensure the provided
        model ID and organization/project IDs are valid to avoid errors during the simulation start.
        Clients can use /stop endpoint to stop the simulation.
    """
    return run_simulation(
        org_id=org_id,
        project_id=project_id,
        model_self=model_self,
        config=request.config,
        autosave=request.autosave,
        token=token,
    )


@router.post(
    "/single-neuron/{org_id}/{project_id}/{task_id}/stop",
    summary=(
        """
        Stops a running simulation identified by the given task ID
        """
    ),
)
async def kill_simulation(
    org_id: str,
    project_id: str,
    task_id: str,
    token: str = Depends(verify_jwt),
):
    """

    This endpoint can only stop simulations that were started using the
    `/run-realtime` endpoint.

    Args:

        org_id (str): The unique identifier for the organization
                       that owns the simulation.

        project_id (str): The unique identifier for the project
                          under which the simulation was created.

        task_id (str): The unique identifier for the simulation
                       task that needs to be stopped.

    Returns:

        StopSimulationResponse: A response indicating whether the simulation
                      was successfully stopped.

    Notes:

        only available when simulation started by the /run-realtime endpoint

    """
    return await stop_simulation(
        token=token,
        task_id=task_id,
    )


@router.post(
    "/single-neuron/{org_id}/{project_id}/launch",
    summary="Launches a simulation as a background task for a specified model",
)
async def launch_simulation(
    model_self: str,
    org_id: str,
    project_id: str,
    config: SingleNeuronSimulationConfig,
    response: Response,
    token: str = Depends(verify_jwt),
) -> SimulationResultItemResponse:
    """
    This endpoint allows users to initiate a simulation which will be processed
    in the background.

    Args:

        model_self (str): The unique identifier of the model for which the simulation
                          is to be launched.

        org_id (str): The unique identifier of the organization that owns the model.

        project_id (str): The unique identifier of the project under which the
                          simulation is to be launched.

        config (SingleNeuronSimulationConfig): The configuration parameters for the
                                               simulation, which must conform to the
                                               `SingleNeuronSimulationConfig` schema.

    Returns:

        SimulationResultItemResponse: A response model containing the result of
                                       the simulation launch, including relevant
                                       details such as the task ID and status.

    Raises:

        BlueNaasError: If there is an error specific to the BlueNaas system during
                       the simulation launch process. The HTTP status code will
                       reflect the nature of the error.

        HTTPException: If there is a general exception during the launch process,
                       an HTTP 500 Internal Server Error will be raised.

    """
    try:
        result = submit_simulation(
            token=token,
            model_self=model_self,
            org_id=org_id,
            project_id=project_id,
            config=config,
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return result
    except BlueNaasError as e:
        response.status_code = e.http_status_code
        raise e
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise e


@router.get(
    "/single-neuron/{org_id}/{project_id}",
    summary=(
        """
        Retrieves all simulations associated with a specific project.
        """
    ),
)
async def get_all_simulations_for_project(
    org_id: str,
    project_id: str,
    simulation_type: Optional[SimulationType] = None,
    page_offset: int = 0,
    page_size: int = 20,
    created_at_start: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    created_at_end: Optional[datetime] = Query(
        None, description="Filter by createdAt date (YYYY-MM-DDTHH:MM:SSZ)"
    ),
    token: str = Depends(verify_jwt),
) -> PaginatedSimulationsResponse:
    """
    This endpoint allows users to fetch all simulations for a given project,
    identified by the organization ID and project ID. The results are paginated,
    and users can filter the simulations based on their creation dates and simulation type.

    Args:

        org_id (str): The unique identifier of the organization that owns the project.

        project_id (str): The unique identifier of the project from which to retrieve
                          simulations.

        simulation_type (Optional[SimulationType]): An optional filter to specify the type
                                                    of simulations to retrieve. If not provided,
                                                    all simulation types will be returned.

        page_offset (int): The number of simulations to skip before starting to collect the
                           result set. Default is 0.

        page_size (int): The maximum number of simulations to return in the response.
                         Default is 20.

        created_at_start (Optional[datetime]): An optional start date for filtering simulations
                                                created after this date (inclusive).
                                                Should follow the format YYYY-MM-DDTHH:MM:SSZ.

        created_at_end (Optional[datetime]): An optional end date for filtering simulations
                                              created before this date (inclusive).
                                              Should follow the format YYYY-MM-DDTHH:MM:SSZ.

    Returns:

        PaginatedSimulationsResponse: A response model containing a paginated list of
        simulations related to the specified project.

    Notes:

        Simulation results (x, y points) are not included in the response to avoid
        excessive data transfer.

    """
    return fetch_all_simulations_of_project(
        token=token,
        org_id=org_id,
        project_id=project_id,
        sim_type=simulation_type,
        offset=page_offset,
        size=page_size,
        created_at_start=created_at_start,
        created_at_end=created_at_end,
    )


@router.get(
    "/single-neuron/{org_id}/{project_id}/{simulation_uri}",
    summary=(
        """
        Retrieves the results, status and metadata of a previously completed simulation.
        """
    ),
)
async def get_simulation(
    org_id: str,
    project_id: str,
    simulation_uri: str = Path(
        ..., description="URL-encoded simulation URI (resource ID in nexus context)"
    ),
    token: str = Depends(verify_jwt),
) -> SimulationResultItemResponse:
    """
    Retrieves the results, status and metadata of a previously completed simulation.

    This endpoint allows users to fetch the results and current status of a simulation
    identified by its URI. If the simulation is still in progress, the results will be
    returned as null. The organization ID and project ID are required to locate the
    specific simulation context.

    Args:

        org_id (str): The unique identifier of the organization that owns the simulation.

        project_id (str): The unique identifier of the project to which the simulation
                          belongs.

        simulation_uri (str): The URL-encoded simulation URI (resource ID) used to
                              identify the specific simulation. This is passed as a
                              path parameter.

    Returns:

        SimulationResultItemResponse: A response model containing the status and results
                                       of the requested simulation.

    """
    return fetch_simulation_status_and_results(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_uri,
    )


@router.delete(
    "/single-neuron/{org_id}/{project_id}/{simulation_uri}",
    summary="Deletes a simulation resource identified by its URI (resource ID in nexus context)",
)
async def delete_simulation(
    org_id: str,
    project_id: str,
    simulation_uri: str = Path(
        ..., description="URL-encoded simulation URI (resource ID in nexus context)"
    ),
    token: str = Depends(verify_jwt),
) -> DeprecateNexusResponse:
    """
    This endpoint allows users to delete a specific simulation resource
    based on the provided organization ID, project ID, and simulation URI.
    Once deleted, the simulation resource will no longer be accessible.

    Args:

        org_id (str): The unique identifier of the organization that owns
                       the simulation.

        project_id (str): The unique identifier of the project to which
                          the simulation belongs.

        simulation_uri (str): The URL-encoded simulation URI (resource ID)
                              used to identify the specific simulation.

    Returns:

        DeprecateNexusResponse: A response model indicating the result of
                                the deletion operation.
    """
    return deprecate_simulation(
        token=token,
        org_id=org_id,
        project_id=project_id,
        simulation_uri=simulation_uri,
    )
