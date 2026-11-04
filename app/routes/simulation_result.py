from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from app.domains.simulation_result.lfp_summary import LfpSummaryStatus
from app.routes.dependencies import ProjectContextDep, UserAuthDep
from app.infrastructure.storage.lfp_summary import INDEX_FILE_NAME, SUMMARY_FILE_NAME
from app.services.api.simulation_result.lfp_summary import (
    get_lfp_summary_file,
    get_lfp_summary_status,
)

router = APIRouter(prefix="/simulation-result")


@router.post(
    "/{result_id}/lfp-summary",
    tags=["simulation-result", "lfp-summary"],
    description="The state of an LFP report's summary. Queues its build if it isn't built",
)
async def request_lfp_summary(
    result_id: UUID,
    asset: UUID,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
) -> LfpSummaryStatus:
    return await get_lfp_summary_status(
        result_id, asset, auth=auth, project_context=project_context
    )


@router.get(
    "/{result_id}/lfp-summary",
    tags=["simulation-result", "lfp-summary"],
    description="The LFP report's summary h5, once it is built, with range requests. With "
    "If-Match, only the summary of that ETag",
    response_class=FileResponse,
)
async def download_lfp_summary(
    result_id: UUID,
    asset: UUID,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
    request: Request,
) -> Response:
    return await get_lfp_summary_file(
        result_id,
        asset,
        SUMMARY_FILE_NAME,
        "application/x-hdf5",
        if_match=request.headers.get("if-match"),
        auth=auth,
        project_context=project_context,
    )


@router.get(
    "/{result_id}/lfp-summary/index",
    tags=["simulation-result", "lfp-summary"],
    description="Where each dataset of the LFP report's summary lies in its h5, once it is built",
    response_class=FileResponse,
)
async def download_lfp_summary_index(
    result_id: UUID,
    asset: UUID,
    project_context: ProjectContextDep,
    auth: UserAuthDep,
    request: Request,
) -> Response:
    return await get_lfp_summary_file(
        result_id,
        asset,
        INDEX_FILE_NAME,
        "application/json",
        if_match=request.headers.get("if-match"),
        auth=auth,
        project_context=project_context,
    )
