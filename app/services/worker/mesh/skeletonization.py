from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from entitysdk import Client, ProjectContext
from entitysdk.models import SkeletonizationExecution
from entitysdk.types import ActivityStatus
from httpx import Client as HttpxClient
from httpx import Timeout
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError

from app.config.settings import settings
from app.core.exceptions import AppError, AppErrorCode
from app.core.mesh.analysis import Analysis
from app.core.mesh.skeletonization import Skeletonization
from app.domains.auth import Auth
from app.domains.job import JobStatus
from app.domains.mesh.skeletonization import (
    SkeletonizationInputParams,
    SkeletonizationJobOutput,
    SkeletonizationUltraliserParams,
)
from app.infrastructure.accounting.session import accounting_session_factory
from app.utils.rq_job import get_current_job_stream
from app.utils.safe_process import SafeProcessRuntimeError


def run_mesh_skeletonization(
    em_cell_mesh_id: UUID,
    input_params: SkeletonizationInputParams,
    ultraliser_params: SkeletonizationUltraliserParams,
    *,
    execution_id: UUID,
    auth: Auth,
    project_context: ProjectContext,
) -> SkeletonizationJobOutput:
    job_stream = get_current_job_stream()

    httpx_client = HttpxClient(timeout=Timeout(10, read=20))

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
        http_client=httpx_client,
    )

    def set_activity_status(status: ActivityStatus):
        client.update_entity(
            entity_id=execution_id,
            entity_type=SkeletonizationExecution,
            attrs_or_entity={
                "status": status,
            },
        )

    def set_error_activity_state():
        client.update_entity(
            entity_id=execution_id,
            entity_type=SkeletonizationExecution,
            attrs_or_entity={
                "end_time": datetime.now(UTC),
                "status": ActivityStatus.error,
            },
        )

    logger.info(f"Starting analysis for mesh {em_cell_mesh_id}")

    analysis = Analysis(em_cell_mesh_id, client=client)

    try:
        analysis.init()
        analysis_result = analysis.run()
    except Exception as e:
        logger.exception(e)
        raise

    logger.info(f"Analysis completed for mesh {em_cell_mesh_id}")

    accounting_count = analysis_result.approximate_volume

    skeletonization = Skeletonization(
        em_cell_mesh_id,
        input_params,
        ultraliser_params,
        client=client,
        execution_id=execution_id,
    )
    skeletonization.init()

    logger.info("Making accounting reservation for neuron mesh skeletonization")
    logger.info(f"Accounting mesh factor: {accounting_count}")

    accounting_session = accounting_session_factory.oneshot_session(
        subtype=ServiceSubtype.NEURON_MESH_SKELETONIZATION,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=accounting_count,
        name=skeletonization.mesh.metadata.name,
    )

    def cleanup_execution_entity():
        logger.warning("Cleaning up execution entity due to a pre-run exception")
        client.delete_entity(
            entity_id=execution_id,
            entity_type=SkeletonizationExecution,
        )

    try:
        accounting_session.make_reservation()
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        cleanup_execution_entity()
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the neuron mesh skeletonization",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.warning(f"Accounting service error: {ex}")
        cleanup_execution_entity()
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex

    set_activity_status(ActivityStatus.running)
    job_stream.send_status(JobStatus.running)

    try:
        skeletonization.init()
        skeletonization.run()
        skeletonization.output.post_process()
        morphology = skeletonization.output.upload()

        client.update_entity(
            entity_id=execution_id,
            entity_type=SkeletonizationExecution,
            attrs_or_entity={
                "generated_ids": [morphology.id],
                "end_time": datetime.now(UTC),
                "status": ActivityStatus.done,
            },
        )
    except SafeProcessRuntimeError as e:
        logger.error(f"Skeletonization failed: {e}")
        set_error_activity_state()
        accounting_session.finish(exc_type=e)  # type: ignore
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        set_error_activity_state()
        accounting_session.finish(exc_type=e)  # type: ignore
        raise
    finally:
        skeletonization.output.cleanup()
        httpx_client.close()

    logger.info(f"Skeletonization completed for mesh {em_cell_mesh_id}")

    try:
        accounting_session.finish()
        logger.debug("Accounting session finished successfully")
    except Exception as e:
        # TODO Report to Sentry
        logger.error(f"Accounting session closure failed: {e}")

    return SkeletonizationJobOutput(
        morphology=morphology,
    )
