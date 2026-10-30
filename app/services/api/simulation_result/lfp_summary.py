from http import HTTPStatus
from uuid import UUID

import httpx
from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models import SimulationResult
from entitysdk.models.asset import Asset
from entitysdk.route import get_assets_endpoint
from entitysdk.types import AssetLabel
from fastapi.responses import FileResponse
from rq.job import JobStatus

from app.config.settings import settings
from app.core.exceptions import AppError
from app.domains.simulation_result.lfp_summary import (
    LfpSummaryState,
    LfpSummaryStatus,
    NoSummaryReason,
)
from app.infrastructure.kc.auth import Auth
from app.infrastructure.rq import get_queue
from app.infrastructure.storage.epoch import CacheKind, ensure_epoch, get_epoch
from app.infrastructure.storage.lfp_summary import (
    BUILD_QUEUES,
    INDEX_FILE_NAME,
    LIVE_STATUSES,
    MAX_REPORT_BYTES,
    SUMMARY_FILE_NAME,
    build_job_id,
    build_queue,
    enqueue_build,
    read_no_summary_reason,
    read_summary_info,
    summary_dir,
)
from app.infrastructure.storage.morphology_pack import clean_up_abandoned_builds
from app.utils.asyncio import run_async

# launch-system labels every report `voltage_report`, LFP included
LFP_REPORT_LABELS = frozenset({AssetLabel.lfp_report, AssetLabel.voltage_report})


def _not_found(message: str) -> AppError:
    return AppError(message=message, error_code=None, http_status_code=HTTPStatus.NOT_FOUND)


def _get_report(
    result_id: UUID, asset_id: UUID, *, auth: Auth, project_context: ProjectContext
) -> Asset:
    """The result's report asset, as the user may see it. The cache is shared by everyone, so it is
    only read for a report the user has access to.
    """
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )
    try:
        result = client.get_entity(result_id, entity_type=SimulationResult)
    except EntitySDKError as ex:
        cause = ex.__cause__
        if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code in (
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
            HTTPStatus.NOT_FOUND,
        ):
            raise _not_found("Simulation result not found") from ex
        raise
    asset = next((a for a in result.assets or [] if a.id == asset_id), None)
    if asset is None:
        raise _not_found("The simulation result has no such asset")
    return asset


def _download_url(
    result_id: UUID, asset_id: UUID, *, access_token: str, project_context: ProjectContext
) -> str:
    """The presigned URL entitycore redirects the asset's download to, which the job reads by range
    without a token of the user's.
    """
    endpoint = get_assets_endpoint(
        api_url=str(settings.ENTITYCORE_URI),
        entity_type=SimulationResult,
        entity_id=result_id,
        asset_id=asset_id,
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "project-id": str(project_context.project_id),
    }
    if project_context.virtual_lab_id:
        headers["virtual-lab-id"] = str(project_context.virtual_lab_id)
    response = httpx.get(f"{endpoint}/download", headers=headers, timeout=30)
    if not response.is_redirect or "location" not in response.headers:
        raise AppError(
            message="The report's download URL could not be read",
            error_code=None,
            http_status_code=HTTPStatus.BAD_GATEWAY,
        )
    return response.headers["location"]


def _status_in_cache(epoch: str, asset_id: UUID) -> LfpSummaryStatus | None:
    directory = summary_dir(epoch, asset_id)
    if info := read_summary_info(directory):
        return LfpSummaryStatus(state=LfpSummaryState.READY, size=info.size, sha256=info.sha256)
    if reason := read_no_summary_reason(directory):
        return LfpSummaryStatus(state=LfpSummaryState.REFUSED, reason=reason)
    return None


def _get_or_build_summary(
    result_id: UUID, report: Asset, *, access_token: str, project_context: ProjectContext
) -> LfpSummaryStatus:
    if report.label not in LFP_REPORT_LABELS or report.is_directory:
        return LfpSummaryStatus(
            state=LfpSummaryState.REFUSED, reason=NoSummaryReason.NOT_LFP_REPORT
        )
    if report.size > MAX_REPORT_BYTES:
        return LfpSummaryStatus(state=LfpSummaryState.REFUSED, reason=NoSummaryReason.TOO_LARGE)

    epoch = ensure_epoch(CacheKind.LFP_SUMMARY)
    if status := _status_in_cache(epoch, report.id):
        return status

    clean_up_abandoned_builds()

    failed = False
    for queue in BUILD_QUEUES:
        job = get_queue(queue).fetch_job(build_job_id(epoch, report.id, queue))
        if job is None:
            continue
        status = job.get_status(refresh=False)
        if status in LIVE_STATUSES:
            return LfpSummaryStatus(
                state=LfpSummaryState.BUILDING, queue_position=job.get_position()
            )
        failed = failed or status == JobStatus.FAILED

    # A build may have finished since the cache was read
    if status := _status_in_cache(epoch, report.id):
        return status

    # A failed job is kept for a day, and only then is the report summarised again
    if failed:
        return LfpSummaryStatus(state=LfpSummaryState.FAILED)

    enqueue_build(
        build_queue(report.size),
        epoch=epoch,
        asset_id=report.id,
        url=_download_url(
            result_id, report.id, access_token=access_token, project_context=project_context
        ),
        size=report.size,
    )
    return LfpSummaryStatus(state=LfpSummaryState.BUILDING)


async def get_lfp_summary_status(
    result_id: UUID, asset_id: UUID, *, auth: Auth, project_context: ProjectContext
) -> LfpSummaryStatus:
    """The state of the report's summary. A build is queued if the summary is not built yet."""
    report = await run_async(
        lambda: _get_report(result_id, asset_id, auth=auth, project_context=project_context)
    )
    return await run_async(
        lambda: _get_or_build_summary(
            result_id, report, access_token=auth.access_token, project_context=project_context
        )
    )


def _matches(if_match: str | None, etag: str) -> bool:
    if if_match is None or if_match.strip() == "*":
        return True
    return etag in (tag.strip() for tag in if_match.split(","))


def _summary_file_response(
    asset_id: UUID, name: str, media_type: str, if_match: str | None
) -> FileResponse:
    epoch = get_epoch(CacheKind.LFP_SUMMARY)
    directory = summary_dir(epoch, asset_id) if epoch else None
    info = read_summary_info(directory) if directory else None
    if directory is None or info is None:
        raise _not_found("The report's LFP summary is not built")
    etag = f'"{info.sha256}"'
    # Else a reader holding a rebuilt summary's index would read its bytes at the old offsets
    if not _matches(if_match, etag):
        raise AppError(
            message="The report's LFP summary has changed",
            error_code=None,
            http_status_code=HTTPStatus.PRECONDITION_FAILED,
        )
    return FileResponse(directory / name, media_type=media_type, headers={"ETag": etag})


async def get_lfp_summary(
    result_id: UUID,
    asset_id: UUID,
    *,
    if_match: str | None,
    auth: Auth,
    project_context: ProjectContext,
) -> FileResponse:
    """The report's summary h5, if it is built. Never queues a build."""
    await run_async(
        lambda: _get_report(result_id, asset_id, auth=auth, project_context=project_context)
    )
    return await run_async(
        lambda: _summary_file_response(asset_id, SUMMARY_FILE_NAME, "application/x-hdf5", if_match)
    )


async def get_lfp_summary_index(
    result_id: UUID,
    asset_id: UUID,
    *,
    if_match: str | None,
    auth: Auth,
    project_context: ProjectContext,
) -> FileResponse:
    """The index of the report's summary, if it is built. Never queues a build."""
    await run_async(
        lambda: _get_report(result_id, asset_id, auth=auth, project_context=project_context)
    )
    return await run_async(
        lambda: _summary_file_response(asset_id, INDEX_FILE_NAME, "application/json", if_match)
    )
