import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from entitysdk.types import CircuitScale
from filelock import FileLock, Timeout
from rq import SimpleWorker
from rq.job import JobStatus

from app.config.settings import settings
from app.constants import CIRCUIT_CONFIG_NAME, DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.morphology_pack.build import NoPackError, PackTooLargeError
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch
from app.infrastructure.storage.morphology_pack import (
    NO_PACK_FILE_NAME,
    PACK_FILE_NAME,
    PACK_INFO_FILE_NAME,
    build_job_id,
    enqueue_build,
    pack_dir,
)
from app.services.worker.circuit import morphology_pack as service
from tests.infrastructure.storage.morphology_pack_case import MorphologyPackTestCase, circuit_of

PACK = b"a pack"
GB = 2**30


class TestBuildMorphologyPack(MorphologyPackTestCase):
    def setUp(self):
        super().setUp()
        self.circuit = circuit_of(100)

        patcher = patch.object(service, "Client")
        self.client = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.client.get_entity.return_value = self.circuit

        self.staged_into: list[Path] = []
        patcher = patch.object(
            service, "stage_morphology_pack_inputs", side_effect=self.stage_partially
        )
        self.stage = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(service, "build_morphology_pack", return_value=PACK)
        self.build_pack = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(service, "segment_cap", return_value=1_000)
        self.segment_cap = patcher.start()
        self.addCleanup(patcher.stop)

    def stage_partially(self, client, circuit, directory: Path) -> Path:
        self.staged_into.append(directory)
        (directory / CIRCUIT_CONFIG_NAME).write_text("{}")
        return directory / CIRCUIT_CONFIG_NAME

    def run_build(self, queue: JobQueue = JobQueue.LOW, epoch: str | None = None):
        epoch = epoch or self.epoch()
        service.build_circuit_morphology_pack(
            self.circuit.id,
            epoch=epoch,
            queue=queue,
            job_id=build_job_id(epoch, self.circuit.id, queue),
            access_token="token",
            project_context=self.project_context,
        )

    def directory(self) -> Path:
        return pack_dir(self.epoch(), self.circuit.id)

    def test_a_build_writes_the_pack_then_its_info_then_ready(self):
        def check_the_pack_is_there_before(directory, info):
            self.assertEqual((directory / PACK_FILE_NAME).read_bytes(), PACK)
            self.assertFalse((directory / READY_MARKER_FILE_NAME).exists())
            write_pack_info(directory, info)

        write_pack_info = service.write_pack_info
        with patch.object(service, "write_pack_info", side_effect=check_the_pack_is_there_before):
            self.run_build()

        directory = self.directory()
        self.assertTrue((directory / READY_MARKER_FILE_NAME).exists())
        self.assertEqual(
            json.loads((directory / PACK_INFO_FILE_NAME).read_text()),
            {"size": len(PACK), "sha256": hashlib.sha256(PACK).hexdigest(), "queue": "low"},
        )
        self.assertEqual(list(directory.glob("*.tmp")), [])
        FileLock(directory / DIR_LOCK_FILE_NAME).acquire(timeout=0)

    def test_nothing_is_done_once_settled(self):
        for marker in [READY_MARKER_FILE_NAME, NO_PACK_FILE_NAME]:
            with self.subTest(marker=marker):
                directory = self.directory()
                directory.mkdir(parents=True, exist_ok=True)
                (directory / marker).touch()

                self.run_build()

                self.build_pack.assert_not_called()
                (directory / marker).unlink()

    def test_nothing_is_done_while_another_build_holds_the_lock(self):
        directory = self.directory()
        directory.mkdir(parents=True)
        holder = FileLock(directory / DIR_LOCK_FILE_NAME)
        holder.acquire()
        self.addCleanup(holder.release)

        self.run_build()

        self.build_pack.assert_not_called()
        self.client.get_entity.assert_not_called()

    def test_nothing_is_done_in_a_cache_cleared_since(self):
        epoch = self.epoch()
        rotate_epoch(CacheKind.MORPHOLOGY_PACK)

        self.run_build(epoch=epoch)

        self.build_pack.assert_not_called()
        self.assertEqual(list(self.storage.iterdir()), [])

    def test_a_lock_file_unlinked_under_a_dead_holder_is_taken_anew(self):
        directory = self.directory()
        directory.mkdir(parents=True)
        lock_file = directory / DIR_LOCK_FILE_NAME
        dead = FileLock(lock_file)
        dead.acquire()
        self.addCleanup(dead.release)

        with self.assertRaises(Timeout):
            FileLock(lock_file).acquire(timeout=0)

        os.unlink(lock_file)
        newcomer = FileLock(lock_file)
        newcomer.acquire(timeout=0)
        newcomer.release()

    def test_no_morphologies(self):
        self.build_pack.side_effect = NoPackError("None of the morphologies could be read")

        self.run_build(JobQueue.CPU4_MEM16)

        marker = json.loads((self.directory() / NO_PACK_FILE_NAME).read_text())
        self.assertEqual(marker["reason"], "no_morphologies")
        self.assertFalse((self.directory() / READY_MARKER_FILE_NAME).exists())

    def test_too_large_for_the_largest_queue(self):
        self.build_pack.side_effect = PackTooLargeError("over the cap")

        self.run_build(JobQueue.CPU4_MEM16)

        marker = json.loads((self.directory() / NO_PACK_FILE_NAME).read_text())
        self.assertEqual(marker["reason"], "too_large")

    def test_too_large_for_low_is_moved_once_the_lock_is_free(self):
        self.build_pack.side_effect = PackTooLargeError("over the cap")

        def check_the_lock_is_free(*args, **kwargs):
            FileLock(self.directory() / DIR_LOCK_FILE_NAME).acquire(timeout=0)
            return enqueue_build(*args, **kwargs)

        with patch.object(service, "enqueue_build", side_effect=check_the_lock_is_free):
            self.run_build(JobQueue.LOW)

        self.assertEqual(
            self.queued_ids(JobQueue.CPU4_MEM16),
            [build_job_id(self.epoch(), self.circuit.id, JobQueue.CPU4_MEM16)],
        )
        self.assertFalse((self.directory() / NO_PACK_FILE_NAME).exists())

    def test_the_budget_is_one_worker_share_of_the_task(self):
        with (
            patch.object(service, "memory_limit", return_value=16 * GB),
            patch.object(service, "available_cpus", return_value=8),
            patch.object(settings, "NUM_WORKERS", 4),
        ):
            self.run_build()

        self.segment_cap.assert_called_once_with(limit=4 * GB, workers=2)
        self.assertEqual(self.build_pack.call_args.args[1:], (1_000, 2))

    def test_a_simulated_scale_is_staged_whole_into_the_circuit_cache(self):
        for scale in [CircuitScale.pair, CircuitScale.small]:
            with self.subTest(scale=scale):
                self.circuit.scale = scale
                with patch.object(service, "Circuit") as circuit_class:
                    circuit_class.return_value.path = Path("/circuit-cache/circuit")

                    self.run_build()

                circuit_class.return_value.init.assert_called_once()
                self.assertEqual(
                    self.build_pack.call_args.args[0],
                    Path("/circuit-cache/circuit") / CIRCUIT_CONFIG_NAME,
                )
                self.stage.assert_not_called()
                (self.directory() / READY_MARKER_FILE_NAME).unlink()

    def test_a_microcircuit_is_staged_on_local_disk_and_removed(self):
        self.run_build()

        (staged,) = self.staged_into
        self.assertTrue(staged.is_relative_to(Path(tempfile.gettempdir())))
        self.assertFalse(staged.is_relative_to(self.storage))
        self.assertFalse(staged.exists())
        self.assertEqual(self.build_pack.call_args.args[0], staged / CIRCUIT_CONFIG_NAME)
        self.assertFalse((self.storage / CacheKind.CIRCUIT.value).exists())

    def test_a_microcircuit_stage_is_removed_after_a_failure(self):
        self.build_pack.side_effect = RuntimeError("killed")

        with self.assertRaises(RuntimeError):
            self.run_build()

        (staged,) = self.staged_into
        self.assertFalse(staged.exists())

    def test_a_microcircuit_already_in_the_circuit_cache_is_read_from_there(self):
        cached = (
            service.epoch_root(CacheKind.CIRCUIT) / "model" / service.uuid_subpath(self.circuit.id)
        )
        cached.mkdir(parents=True)
        (cached / READY_MARKER_FILE_NAME).touch()

        self.run_build()

        self.stage.assert_not_called()
        self.assertEqual(self.build_pack.call_args.args[0], cached / CIRCUIT_CONFIG_NAME)


class TestFailedBuildInTheWorker(MorphologyPackTestCase):
    def test_a_failure_frees_the_lock_and_the_job_is_retried_once(self):
        circuit = circuit_of(100)
        epoch = self.epoch()
        job = enqueue_build(
            JobQueue.LOW,
            epoch=epoch,
            circuit_id=circuit.id,
            access_token="token",
            project_context=self.project_context,
        )
        assert job is not None
        directory = pack_dir(epoch, circuit.id)

        def fail(circuit_id, directory, *, job_id, **kwargs):
            (directory / f"{PACK_FILE_NAME}.{job_id}.tmp").write_bytes(b"part")
            raise RuntimeError("the build failed")

        with (
            patch.object(service, "Client"),
            patch.object(service, "_build", side_effect=fail) as build,
        ):
            # A burst worker runs the retry too
            SimpleWorker([get_queue(JobQueue.LOW)], connection=self.redis).work(burst=True)

        self.assertEqual(build.call_count, 2)
        job = get_queue(JobQueue.LOW).fetch_job(job.id)
        assert job is not None
        self.assertEqual(job.get_status(), JobStatus.FAILED)
        self.assertEqual(job.retries_left, 0)
        self.assertEqual(list(directory.iterdir()), [])
