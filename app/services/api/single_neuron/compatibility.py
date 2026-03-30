from uuid import UUID

from entitysdk import ProjectContext
from rq import Queue

from app.core.api import ApiResponse
from app.domains.neuron_model import CompatibilityCheckResponse
from app.job import JobFn
from app.utils.rq_job import dispatch, get_job_data


async def check_compatibility_service(
    morphology_id: UUID,
    emodel_id: UUID,
    *,
    job_queue: Queue,
    access_token: str,
    project_context: ProjectContext,
) -> ApiResponse[CompatibilityCheckResponse]:
    _job, stream = await dispatch(
        job_queue,
        JobFn.CHECK_COMPATIBILITY,
        job_args=(morphology_id, emodel_id),
        job_kwargs={
            "access_token": access_token,
            "project_context": project_context,
        },
    )

    result = await get_job_data(stream)

    return ApiResponse[CompatibilityCheckResponse](
        message="Compatibility check completed",
        data=CompatibilityCheckResponse(**result),
    )
