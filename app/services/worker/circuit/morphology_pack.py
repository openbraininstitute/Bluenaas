import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from entitysdk import Client, ProjectContext
from entitysdk.models import Circuit as EntitycoreCircuit
from entitysdk.types import CircuitScale
from filelock import FileLock, Timeout
from loguru import logger

from app.config.settings import settings
from app.constants import CIRCUIT_CONFIG_NAME, DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.circuit.circuit import Circuit
from app.core.morphology_pack.build import (
    NoPackError,
    PackTooLargeError,
    build_morphology_pack,
    segment_cap,
)
from app.core.morphology_pack.staging import stage_morphology_pack_inputs
from app.domains.circuit.morphology_pack import NoPackReason
from app.infrastructure.rq import JobQueue
from app.infrastructure.storage import epoch_root, rm_dir, uuid_subpath
from app.infrastructure.storage.epoch import CacheKind, current_epoch
from app.infrastructure.storage.morphology_pack import (
    NO_PACK_FILE_NAME,
    PACK_FILE_NAME,
    PackInfo,
    enqueue_build,
    pack_dir,
    write_no_pack,
    write_pack_info,
)
from app.utils.memory import memory_limit
from app.utils.parallel import available_cpus

# The scales Bluenaas simulates: they are staged whole into the circuit cache, as a simulation
# stages them, so that a simulation of the circuit finds it there.
SIMULATED_SCALES = frozenset({CircuitScale.pair, CircuitScale.small})


def _slot() -> tuple[int, int]:
    """The memory and the processes of this worker's share of its task."""
    return (
        memory_limit() // settings.NUM_WORKERS,
        max(1, available_cpus() // settings.NUM_WORKERS),
    )


@contextmanager
def _staged(circuit: EntitycoreCircuit, client: Client) -> Iterator[Path]:
    """The path of the circuit's config, with the files the pack is built from beside it."""
    assert circuit.id is not None
    if circuit.scale in SIMULATED_SCALES:
        simulated = Circuit(circuit.id, client=client)
        simulated.init()
        yield simulated.path / CIRCUIT_CONFIG_NAME
        return

    # Read where a simulation staged the circuit whole, but never written there: a partial stage
    # marked ready would break the next simulation.
    cached = epoch_root(CacheKind.CIRCUIT) / "model" / uuid_subpath(circuit.id)
    if (cached / READY_MARKER_FILE_NAME).exists():
        yield cached / CIRCUIT_CONFIG_NAME
        return

    # On the task's own disk, which goes with the task if it is killed
    directory = Path(tempfile.mkdtemp(prefix="morphology-pack-"))
    try:
        yield stage_morphology_pack_inputs(client, circuit, directory)
    finally:
        rm_dir(directory)


def _is_settled(directory: Path) -> bool:
    return (directory / READY_MARKER_FILE_NAME).exists() or (directory / NO_PACK_FILE_NAME).exists()


def _build(
    circuit_id: UUID,
    directory: Path,
    *,
    queue: JobQueue,
    job_id: str,
    client: Client,
) -> bool:
    """Build the pack, or leave the reason there is none. Returns whether it is too large for this
    queue but not for a larger one.
    """
    circuit = client.get_entity(circuit_id, entity_type=EntitycoreCircuit)
    memory, workers = _slot()
    try:
        with _staged(circuit, client) as config_path:
            pack = build_morphology_pack(
                config_path, segment_cap(limit=memory, workers=workers), workers
            )
    except PackTooLargeError as ex:
        if queue == JobQueue.LOW:
            logger.info(f"The morphology pack of {circuit_id} is too large for {queue.value}")
            return True
        write_no_pack(directory, NoPackReason.TOO_LARGE, str(ex))
        return False
    except NoPackError as ex:
        write_no_pack(directory, NoPackReason.NO_MORPHOLOGIES, str(ex))
        return False

    tmp = directory / f"{PACK_FILE_NAME}.{job_id}.tmp"
    tmp.write_bytes(pack)
    os.replace(tmp, directory / PACK_FILE_NAME)
    write_pack_info(
        directory,
        PackInfo(size=len(pack), sha256=hashlib.sha256(pack).hexdigest(), queue=queue.value),
    )
    (directory / READY_MARKER_FILE_NAME).touch()
    logger.info(f"Morphology pack of {circuit_id} built, {len(pack)} bytes")
    return False


def build_circuit_morphology_pack(
    circuit_id: UUID,
    *,
    epoch: str,
    queue: JobQueue,
    job_id: str,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    """Build the circuit's pack into the cache, unless it is there or another build holds it.

    A build on `low` that goes over its worker's share of the memory is moved to `4cpu-16gb`.
    """
    if current_epoch(CacheKind.MORPHOLOGY_PACK) != epoch:
        # The next request for the pack queues it in the new epoch
        logger.info("The morphology pack cache was cleared since the build was queued")
        return

    directory = pack_dir(epoch, circuit_id)
    directory.mkdir(parents=True, exist_ok=True)
    if _is_settled(directory):
        return

    # Not waiting: a build runs for minutes, and the one holding the lock builds the same pack
    lock = FileLock(directory / DIR_LOCK_FILE_NAME)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info(f"Another job is building the morphology pack of {circuit_id}")
        return

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )
    try:
        too_large = not _is_settled(directory) and _build(
            circuit_id, directory, queue=queue, job_id=job_id, client=client
        )
    finally:
        lock.release()

    if too_large:
        # Queued once the lock is free, so the larger build doesn't find it held
        enqueue_build(
            JobQueue.CPU4_MEM16,
            epoch=epoch,
            circuit_id=circuit_id,
            access_token=access_token,
            project_context=project_context,
        )
