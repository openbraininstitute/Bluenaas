from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.domains.simulation_result.lfp_summary import LfpSummaryStatus
from app.routes.dependencies import ProjectContextDep, UserAuthDep
from app.services.api.simulation_result.lfp_summary import (
    get_lfp_summary,
    get_lfp_summary_index,
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
) -> FileResponse:
    return await get_lfp_summary(
        result_id,
        asset,
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
) -> FileResponse:
    return await get_lfp_summary_index(
        result_id,
        asset,
        if_match=request.headers.get("if-match"),
        auth=auth,
        project_context=project_context,
    )
