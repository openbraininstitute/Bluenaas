from http import HTTPStatus
from uuid import UUID

from entitysdk import Client
from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models import Circuit
from entitysdk.types import CircuitScale
from fastapi.responses import FileResponse
from httpx import HTTPStatusError
from rq.job import JobStatus

from app.config.settings import settings
from app.core.exceptions import AppError
from app.domains.circuit.morphology_pack import (
    MorphologyPackState,
    MorphologyPackStatus,
    NoPackReason,
)
from app.infrastructure.kc.auth import Auth
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage.epoch import CacheKind, ensure_epoch, get_epoch
from app.infrastructure.storage.morphology_pack import (
    BUILD_QUEUES,
    LIVE_STATUSES,
    MAX_NEURONS,
    PACK_FILE_NAME,
    SMALL_BUILD_MAX_NEURONS,
    build_job_id,
    clean_up_abandoned_builds,
    enqueue_build,
    pack_dir,
    read_no_pack_reason,
    read_pack_info,
)
from app.utils.asyncio import run_async


def _get_circuit(circuit_id: UUID, *, auth: Auth, project_context: ProjectContext) -> Circuit:
    """The circuit, as the user may see it. The cache is shared by everyone, so it is only read
    for a circuit the user has access to.
    """
    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )
    try:
        return client.get_entity(circuit_id, entity_type=Circuit)
    except EntitySDKError as ex:
        cause = ex.__cause__
        if isinstance(cause, HTTPStatusError) and cause.response.status_code in (
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
            HTTPStatus.NOT_FOUND,
        ):
            raise AppError(
                message="Circuit not found",
                error_code=None,
                http_status_code=HTTPStatus.NOT_FOUND,
            ) from ex
        raise


def _status_in_cache(epoch: str, circuit_id: UUID) -> MorphologyPackStatus | None:
    directory = pack_dir(epoch, circuit_id)
    if info := read_pack_info(directory):
        return MorphologyPackStatus(
            state=MorphologyPackState.READY, size=info.size, sha256=info.sha256
        )
    if reason := read_no_pack_reason(directory):
        return MorphologyPackStatus(state=MorphologyPackState.REFUSED, reason=reason)
    return None


def _get_or_build_pack(
    circuit: Circuit, *, access_token: str, project_context: ProjectContext
) -> MorphologyPackStatus:
    if circuit.scale == CircuitScale.single:
        return MorphologyPackStatus(
            state=MorphologyPackState.REFUSED, reason=NoPackReason.SINGLE_NEURON
        )
    if circuit.number_neurons > MAX_NEURONS:
        return MorphologyPackStatus(
            state=MorphologyPackState.REFUSED, reason=NoPackReason.TOO_LARGE
        )

    assert circuit.id is not None
    epoch = ensure_epoch(CacheKind.MORPHOLOGY_PACK)
    if status := _status_in_cache(epoch, circuit.id):
        return status

    clean_up_abandoned_builds()

    failed = False
    for queue in BUILD_QUEUES:
        job = get_queue(queue).fetch_job(build_job_id(epoch, circuit.id, queue))
        if job is None:
            continue
        status = job.get_status(refresh=False)
        if status in LIVE_STATUSES:
            return MorphologyPackStatus(
                state=MorphologyPackState.BUILDING, queue_position=job.get_position()
            )
        failed = failed or status == JobStatus.FAILED

    # A build may have finished since the cache was read
    if status := _status_in_cache(epoch, circuit.id):
        return status

    # A failed job is kept for a day, and only then is the circuit built again
    if failed:
        return MorphologyPackStatus(state=MorphologyPackState.FAILED)

    enqueue_build(
        JobQueue.LOW if circuit.number_neurons <= SMALL_BUILD_MAX_NEURONS else JobQueue.CPU4_MEM16,
        epoch=epoch,
        circuit_id=circuit.id,
        access_token=access_token,
        project_context=project_context,
    )
    return MorphologyPackStatus(state=MorphologyPackState.BUILDING)


async def get_morphology_pack_status(
    circuit_id: UUID, *, auth: Auth, project_context: ProjectContext
) -> MorphologyPackStatus:
    """The state of the circuit's pack. A build is queued if the pack is not built yet."""
    circuit = await run_async(
        lambda: _get_circuit(circuit_id, auth=auth, project_context=project_context)
    )
    return await run_async(
        lambda: _get_or_build_pack(
            circuit, access_token=auth.access_token, project_context=project_context
        )
    )


def _pack_response(circuit_id: UUID) -> FileResponse:
    epoch = get_epoch(CacheKind.MORPHOLOGY_PACK)
    directory = pack_dir(epoch, circuit_id) if epoch else None
    info = read_pack_info(directory) if directory else None
    if directory is None or info is None:
        raise AppError(
            message="The circuit's morphology pack is not built",
            error_code=None,
            http_status_code=HTTPStatus.NOT_FOUND,
        )
    return FileResponse(
        directory / PACK_FILE_NAME,
        media_type="application/octet-stream",
        headers={"ETag": f'"{info.sha256}"'},
    )


async def get_morphology_pack(
    circuit_id: UUID, *, auth: Auth, project_context: ProjectContext
) -> FileResponse:
    """The circuit's pack, if it is built. Never queues a build."""
    await run_async(lambda: _get_circuit(circuit_id, auth=auth, project_context=project_context))
    return await run_async(lambda: _pack_response(circuit_id))
