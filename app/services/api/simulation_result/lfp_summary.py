import hashlib
import json
import posixpath
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from pathlib import PurePosixPath
from uuid import UUID

import httpx
from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models import Circuit, Simulation, SimulationResult
from entitysdk.models.asset import Asset
from entitysdk.models.core import Identifiable
from entitysdk.route import get_assets_endpoint
from entitysdk.types import AssetLabel
from entitysdk.utils.http import HTTPStatusError, RequestError
from fastapi import BackgroundTasks
from fastapi.responses import FileResponse, Response
from loguru import logger
from rq.job import JobStatus

from app.config.settings import settings
from app.constants import CIRCUIT_CONFIG_NAME
from app.core.exceptions import AppError
from app.domains.simulation_result.lfp_summary import (
    GroupsUnavailable,
    LfpSummaryState,
    LfpSummaryStatus,
    NoSummaryReason,
)
from app.infrastructure.kc.auth import Auth
from app.infrastructure.rq import clean_up_abandoned_jobs, get_queue
from app.infrastructure.storage.epoch import CacheKind, ensure_epoch, get_epoch
from app.infrastructure.storage.lfp_summary import (
    BUILD_QUEUES,
    LIVE_STATUSES,
    MAX_REPORT_BYTES,
    SummaryInfo,
    build_job_id,
    build_queue,
    enqueue_build,
    read_no_summary_reason,
    read_summary_info,
    summary_dir,
)
from app.services.api.entitycore import get_entity_or_not_found, user_client
from app.utils.asyncio import run_async

# launch-system labels every report `voltage_report`, LFP included
LFP_REPORT_LABELS = frozenset({AssetLabel.lfp_report, AssetLabel.voltage_report})


# How long a user's access to a report is taken as found, at most. A viewer reads a summary in many
# requests, and each would ask entitycore again.
ACCESS_SECONDS = 60
ACCESS_ENTRIES = 4096

IN_HAND = LIVE_STATUSES | {JobStatus.FAILED}


def _not_found(message: str) -> AppError:
    return AppError(message=message, error_code=None, http_status_code=HTTPStatus.NOT_FOUND)


class AccessFound:
    """The reports users were found to have access to in the last ACCESS_SECONDS, by their token and
    project, as entitycore answers. Access taken away is seen once the entry is gone.
    """

    def __init__(self):
        self._found: OrderedDict[tuple, tuple[float, SimulationResult, Asset]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(result_id: UUID, asset_id: UUID, auth: Auth, project_context: ProjectContext) -> tuple:
        token = hashlib.sha256(auth.access_token.encode()).hexdigest()
        return (
            token,
            project_context.project_id,
            project_context.virtual_lab_id,
            result_id,
            asset_id,
        )

    def get(self, key: tuple) -> tuple[SimulationResult, Asset] | None:
        with self._lock:
            entry = self._found.get(key)
            if entry is None or entry[0] < time.monotonic():
                return None
            return entry[1], entry[2]

    def add(self, key: tuple, found: tuple[SimulationResult, Asset], token_expires_at: int) -> None:
        seconds = min(ACCESS_SECONDS, token_expires_at - time.time())
        if seconds <= 0:
            return
        with self._lock:
            self._found[key] = (time.monotonic() + seconds, *found)
            self._found.move_to_end(key)
            while len(self._found) > ACCESS_ENTRIES:
                self._found.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._found.clear()


access_found = AccessFound()


def _get_report(
    result_id: UUID, asset_id: UUID, *, auth: Auth, project_context: ProjectContext
) -> tuple[SimulationResult, Asset]:
    """The result and its report asset, as the user may see them. The cache is shared by
    everyone, so it is only read for a report the user has access to.
    """
    key = AccessFound.key(result_id, asset_id, auth, project_context)
    if found := access_found.get(key):
        return found
    result = get_entity_or_not_found(
        user_client(auth.access_token, project_context),
        result_id,
        SimulationResult,
        message="Simulation result not found",
    )
    asset = next((a for a in result.assets or [] if a.id == asset_id), None)
    if asset is None:
        raise _not_found("The simulation result has no such asset")
    access_found.add(key, (result, asset), auth.decoded_token.exp)
    return result, asset


@dataclass
class LfpReport:
    """What a simulation's config says of its LFP report. A summed one holds each population's
    sum over its cells, so it has none to group.
    """

    summed: bool


def _report_entry(
    simulation_id: UUID, report: Asset, *, access_token: str, project_context: ProjectContext
) -> dict | None:
    """The report's entry in the simulation's SONATA config, found by its file's name."""
    client = user_client(access_token, project_context)
    simulation = get_entity_or_not_found(
        client, simulation_id, Simulation, message="Simulation not found"
    )
    config = next(
        (a for a in simulation.assets or [] if a.label == AssetLabel.sonata_simulation_config),
        None,
    )
    if config is None:
        return None
    content = client.download_content(
        entity_id=simulation_id, entity_type=Simulation, asset_id=config.id
    )
    stem = re.sub(r"\.h5$", "", PurePosixPath(report.path).name, flags=re.I)
    try:
        entry = json.loads(content)["reports"].get(stem)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return entry if isinstance(entry, dict) else None


def _lfp_report(
    simulation_id: UUID, report: Asset, *, access_token: str, project_context: ProjectContext
) -> LfpReport | None:
    """An LFP report by its label, or a voltage report whose entry in the simulation's SONATA
    config is of type `lfp`, as the web app reads it. None where it is not one.
    """
    labelled = report.label == AssetLabel.lfp_report
    try:
        entry = _report_entry(
            simulation_id, report, access_token=access_token, project_context=project_context
        )
    except (AppError, EntitySDKError) as ex:
        # One labelled so is an LFP report whatever its config, which is only read for its method
        if not labelled or _may_pass(ex):
            raise
        entry = None
    if not labelled and (entry is None or entry.get("type") != "lfp"):
        return None
    return LfpReport(summed=entry is not None and entry.get("method") == "sum")


def _no_download_url() -> AppError:
    return AppError(
        message="The report's download URL could not be read",
        error_code=None,
        http_status_code=HTTPStatus.BAD_GATEWAY,
    )


def _download_url(
    entity_type: type[Identifiable],
    entity_id: UUID,
    asset_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
    asset_path: str | None = None,
) -> str:
    """The presigned URL entitycore redirects the asset's download to, which the job reads by range
    without a token of the user's.
    """
    endpoint = get_assets_endpoint(
        api_url=str(settings.ENTITYCORE_URI),
        entity_type=entity_type,
        entity_id=entity_id,
        asset_id=asset_id,
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "project-id": str(project_context.project_id),
    }
    if project_context.virtual_lab_id:
        headers["virtual-lab-id"] = str(project_context.virtual_lab_id)
    params = {"asset_path": asset_path} if asset_path else None
    try:
        response = httpx.get(f"{endpoint}/download", headers=headers, params=params, timeout=30)
    except httpx.TransportError as ex:
        raise _no_download_url() from ex
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise _not_found("The asset has no such file")
    if not response.is_redirect or "location" not in response.headers:
        raise _no_download_url()
    return response.headers["location"]


def _expand_manifest(path: str, manifest: dict) -> str:
    for _ in range(len(manifest) + 1):
        path = re.sub(r"\$\w+", lambda m: str(manifest.get(m.group(), m.group())), path)
    return path


def nodes_files(config: dict) -> dict[str, str]:
    """Where each population's nodes file lies within the circuit's directory asset, by its SONATA
    config. Virtual populations are left out, as they report no field, and any file not inside it.
    """
    manifest = config.get("manifest", {})
    files = {}
    for network in config["networks"]["nodes"]:
        path = posixpath.normpath(_expand_manifest(network["nodes_file"], manifest))
        if posixpath.isabs(path) or path.startswith((".", "$")):
            continue
        for population, properties in network["populations"].items():
            if properties.get("type") != "virtual":
                files[population] = path
    return files


def _may_pass(ex: Exception) -> bool:
    """Whether entitycore failed to answer, with a server error or none, and so may yet. A client
    error such as a 404 says it has nothing to give.
    """
    if isinstance(ex, AppError):
        return ex.http_status_code != HTTPStatus.NOT_FOUND
    cause = ex.__cause__
    if isinstance(cause, HTTPStatusError):
        return cause.response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
    return isinstance(cause, RequestError)


@dataclass(frozen=True)
class NodesFiles:
    """A presigned URL of each population's nodes file, and why there are none where that may not be
    so for another user.
    """

    urls: dict[str, str]
    unavailable: GroupsUnavailable | None = None


def _simulated_circuit(client, simulation_id: UUID) -> Circuit | None:
    """The circuit the simulation is of, None where the user can't read it. entitycore answers so for
    a circuit the user may not read as for none, as for a simulation of something else.
    """
    try:
        simulation = get_entity_or_not_found(
            client, simulation_id, Simulation, message="Simulation not found"
        )
        return get_entity_or_not_found(
            client, simulation.entity_id, Circuit, message="Circuit not found"
        )
    except AppError:
        return None


def _nodes_urls(
    simulation_id: UUID, *, access_token: str, project_context: ProjectContext
) -> NodesFiles:
    """A presigned URL of each population's nodes file. None where there are none to find: the
    report is still summarised, without its cells' groups, as a simulation of something other than a
    circuit has none. Where the circuit can't be read it says so, for a user who can read it to have
    the groups built. Raises where they could not be asked for just now, as a summary without groups
    would stay in the cache.
    """
    client = user_client(access_token, project_context)
    try:
        circuit = _simulated_circuit(client, simulation_id)
        if circuit is None:
            logger.info(f"No cell groups for simulation {simulation_id}: its circuit can't be read")
            return NodesFiles({}, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        asset = next(
            (
                a
                for a in circuit.assets or []
                if a.label == AssetLabel.sonata_circuit and a.is_directory
            ),
            None,
        )
        if asset is None:
            logger.info(f"No cell groups for simulation {simulation_id}: no circuit directory")
            return NodesFiles({})
        config = client.download_content(
            entity_id=circuit.id,
            entity_type=Circuit,
            asset_id=asset.id,
            asset_path=CIRCUIT_CONFIG_NAME,
        )
        files = nodes_files(json.loads(config))
        urls = {
            path: _download_url(
                Circuit,
                circuit.id,
                asset.id,
                access_token=access_token,
                project_context=project_context,
                asset_path=path,
            )
            for path in set(files.values())
        }
    except (
        AppError,
        EntitySDKError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ) as ex:
        if _may_pass(ex):
            raise
        logger.info(f"No cell groups for simulation {simulation_id}: {type(ex).__name__}")
        return NodesFiles({})
    return NodesFiles({population: urls[path] for population, path in files.items()})


def _regroup_if_readable(
    epoch: str,
    result_id: UUID,
    simulation_id: UUID,
    report: Asset,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    """Queue the build of a summary again, with its groups, where whoever asked for it first could
    not read its circuit and this user can. It is read as it is until the new one replaces it.
    """
    clean_up_abandoned_jobs(BUILD_QUEUES)
    for queue in BUILD_QUEUES:
        job = get_queue(queue).fetch_job(build_job_id(epoch, report.id, queue, regroup=True))
        # A failed one waits out its FAILED_BUILD_TTL, as a failed build does
        if job is not None and job.get_status(refresh=False) in IN_HAND:
            return
    try:
        # A summed one has no cells to group, whoever can read its circuit
        lfp = _lfp_report(
            simulation_id, report, access_token=access_token, project_context=project_context
        )
        if lfp is None or lfp.summed:
            return
        nodes = _nodes_urls(
            simulation_id, access_token=access_token, project_context=project_context
        )
        # Built again where the circuit can be read but has no groups to give, for the summary to
        # stop saying they'd come
        if nodes.unavailable is not None:
            return
        url = _download_url(
            SimulationResult,
            result_id,
            report.id,
            access_token=access_token,
            project_context=project_context,
        )
    except (AppError, EntitySDKError) as ex:
        # The summary is there to read meanwhile, so this is no reason to fail its status
        logger.info(
            f"The groups of the LFP report {report.id} can't be asked for: {type(ex).__name__}"
        )
        return
    enqueue_build(
        build_queue(report.size),
        epoch=epoch,
        asset_id=report.id,
        url=url,
        size=report.size,
        nodes=nodes.urls,
        regroup=True,
    )


def _ready(info: SummaryInfo) -> LfpSummaryStatus:
    return LfpSummaryStatus(state=LfpSummaryState.READY, size=info.size, sha256=info.sha256)


def _status_in_cache(epoch: str, asset_id: UUID) -> LfpSummaryStatus | None:
    directory = summary_dir(epoch, asset_id)
    if info := read_summary_info(directory):
        return _ready(info)
    if reason := read_no_summary_reason(directory):
        return LfpSummaryStatus(state=LfpSummaryState.REFUSED, reason=reason)
    return None


def _get_or_build_summary(
    result_id: UUID,
    simulation_id: UUID,
    report: Asset,
    *,
    access_token: str,
    project_context: ProjectContext,
    later: Callable[[Callable[[], None]], None],
) -> LfpSummaryStatus:
    if report.label not in LFP_REPORT_LABELS or report.is_directory:
        return LfpSummaryStatus(
            state=LfpSummaryState.REFUSED, reason=NoSummaryReason.NOT_LFP_REPORT
        )
    if report.size > MAX_REPORT_BYTES:
        return LfpSummaryStatus(state=LfpSummaryState.REFUSED, reason=NoSummaryReason.TOO_LARGE)

    epoch = ensure_epoch(CacheKind.LFP_SUMMARY)
    if info := read_summary_info(summary_dir(epoch, report.id)):
        if info.groups_unavailable is not None:
            # Once the status is answered, as the summary is read as it is meanwhile
            later(
                partial(
                    _regroup_if_readable,
                    epoch,
                    result_id,
                    simulation_id,
                    report,
                    access_token=access_token,
                    project_context=project_context,
                )
            )
        return _ready(info)
    if status := _status_in_cache(epoch, report.id):
        return status

    clean_up_abandoned_jobs(BUILD_QUEUES)

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

    # A failed job is kept for FAILED_BUILD_TTL, and only then is the report summarised again
    if failed:
        return LfpSummaryStatus(state=LfpSummaryState.FAILED)

    lfp = _lfp_report(
        simulation_id, report, access_token=access_token, project_context=project_context
    )
    if lfp is None:
        return LfpSummaryStatus(
            state=LfpSummaryState.REFUSED, reason=NoSummaryReason.NOT_LFP_REPORT
        )

    url = _download_url(
        SimulationResult,
        result_id,
        report.id,
        access_token=access_token,
        project_context=project_context,
    )
    nodes = (
        NodesFiles({})
        if lfp.summed
        else _nodes_urls(simulation_id, access_token=access_token, project_context=project_context)
    )
    enqueue_build(
        build_queue(report.size),
        epoch=epoch,
        asset_id=report.id,
        url=url,
        size=report.size,
        nodes=nodes.urls,
        groups_unavailable=nodes.unavailable,
    )
    return LfpSummaryStatus(state=LfpSummaryState.BUILDING)


async def get_lfp_summary_status(
    result_id: UUID,
    asset_id: UUID,
    *,
    auth: Auth,
    project_context: ProjectContext,
    background: BackgroundTasks,
) -> LfpSummaryStatus:
    """The state of the report's summary. A build is queued if the summary is not built yet."""
    result, report = await run_async(
        lambda: _get_report(result_id, asset_id, auth=auth, project_context=project_context)
    )
    return await run_async(
        lambda: _get_or_build_summary(
            result_id,
            result.simulation_id,
            report,
            access_token=auth.access_token,
            project_context=project_context,
            later=background.add_task,
        )
    )


def _matches(if_match: str | None, etag: str) -> bool:
    if if_match is None or if_match.strip() == "*":
        return True
    return etag in (tag.strip() for tag in if_match.split(","))


def _summary_file_response(
    asset_id: UUID, name: str, media_type: str, if_match: str | None
) -> Response:
    epoch = get_epoch(CacheKind.LFP_SUMMARY)
    directory = summary_dir(epoch, asset_id) if epoch else None
    info = read_summary_info(directory) if directory else None
    if directory is None or info is None:
        raise _not_found("The report's LFP summary is not built")
    etag = f'"{info.sha256}"'
    # Else a reader holding a rebuilt summary's index would read its bytes at the old offsets.
    # Not an AppError: this is how a reader learns of a rebuild, and those are logged as errors.
    if not _matches(if_match, etag):
        return Response(status_code=HTTPStatus.PRECONDITION_FAILED)
    return FileResponse(
        info.path(directory, name),
        media_type=media_type,
        headers={"ETag": etag, "Cache-Control": "private, no-cache"},
    )


async def get_lfp_summary_file(
    result_id: UUID,
    asset_id: UUID,
    name: str,
    media_type: str,
    *,
    if_match: str | None,
    auth: Auth,
    project_context: ProjectContext,
) -> Response:
    """A file of the report's summary, the h5 or its index, if it is built. Never queues a
    build.
    """

    def response() -> Response:
        _get_report(result_id, asset_id, auth=auth, project_context=project_context)
        return _summary_file_response(asset_id, name, media_type, if_match)

    return await run_async(response)
