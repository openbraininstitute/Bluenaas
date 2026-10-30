import hashlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from entitysdk.exception import EntitySDKError
from entitysdk.types import CircuitScale
from rq import Callback
from rq.job import JobStatus

from app.constants import DIR_LOCK_FILE_NAME, READY_MARKER_FILE_NAME
from app.core.exceptions import AppError
from app.domains.circuit.morphology_pack import MorphologyPackState, NoPackReason
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage import morphology_pack as storage
from app.infrastructure.storage.epoch import CacheKind, rotate_epoch
from app.infrastructure.storage.morphology_pack import (
    FAILED_BUILD_TTL,
    PACK_FILE_NAME,
    PackInfo,
    build_job_id,
    enqueue_build,
    write_no_pack,
    write_pack_info,
)
from app.services.api.circuit import morphology_pack as service
from tests.infrastructure.storage.morphology_pack_case import MorphologyPackTestCase, circuit_of


def failing_callback(job, connection, exc_type, exc_value, traceback):
    raise RuntimeError("the callback failed")


class TestMorphologyPackStatus(MorphologyPackTestCase):
    def status_of(self, circuit):
        # In a thread, as the route runs it
        with ThreadPoolExecutor(1) as pool:
            return pool.submit(
                service._get_or_build_pack,
                circuit,
                access_token="token",
                project_context=self.project_context,
            ).result()

    def job_of(self, circuit, queue: JobQueue):
        return get_queue(queue).fetch_job(build_job_id(self.epoch(), circuit.id, queue))

    def test_ready(self):
        circuit = circuit_of(100)
        directory = self.pack_dir_of(circuit.id)
        write_pack_info(directory, PackInfo(size=12, sha256="abc", queue="low"))
        (directory / READY_MARKER_FILE_NAME).touch()

        status = self.status_of(circuit)

        self.assertEqual(status.state, MorphologyPackState.READY)
        self.assertEqual((status.size, status.sha256), (12, "abc"))
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_refused_by_its_marker(self):
        circuit = circuit_of(100)
        write_no_pack(self.pack_dir_of(circuit.id), NoPackReason.NO_MORPHOLOGIES, "none read")

        status = self.status_of(circuit)

        self.assertEqual(status.state, MorphologyPackState.REFUSED)
        self.assertEqual(status.reason, NoPackReason.NO_MORPHOLOGIES)

    def test_refused_without_a_job(self):
        for circuit, reason in [
            (circuit_of(1, CircuitScale.single), NoPackReason.SINGLE_NEURON),
            (circuit_of(160_001), NoPackReason.TOO_LARGE),
        ]:
            with self.subTest(reason=reason):
                status = self.status_of(circuit)

                self.assertEqual(status.state, MorphologyPackState.REFUSED)
                self.assertEqual(status.reason, reason)
                self.assertEqual(self.queued_ids(JobQueue.LOW), [])
                self.assertEqual(self.queued_ids(JobQueue.CPU4_MEM16), [])

    def test_the_queue_is_chosen_by_the_neuron_count(self):
        for neurons, queue in [
            (2, JobQueue.LOW),
            (2_000, JobQueue.LOW),
            (2_001, JobQueue.CPU4_MEM16),
            (160_000, JobQueue.CPU4_MEM16),
        ]:
            with self.subTest(neurons=neurons):
                circuit = circuit_of(neurons, CircuitScale.small)

                status = self.status_of(circuit)

                self.assertEqual(status.state, MorphologyPackState.BUILDING)
                self.assertIn(build_job_id(self.epoch(), circuit.id, queue), self.queued_ids(queue))

    def test_the_job_queued(self):
        circuit = circuit_of(100)

        self.status_of(circuit)

        job = self.job_of(circuit, JobQueue.LOW)
        self.assertEqual(job.kwargs["circuit_id"], circuit.id)
        self.assertEqual(job.kwargs["epoch"], self.epoch())
        self.assertEqual(job.kwargs["queue"], "low")
        self.assertEqual(job.retries_left, 1)
        self.assertEqual(job.failure_ttl, FAILED_BUILD_TTL)
        self.assertEqual(
            job.failure_callback,
            storage.remove_build_leftovers,  # type: ignore[attr-defined]
        )

    def test_no_second_job_while_one_is_queued_or_started(self):
        circuit = circuit_of(100)
        self.status_of(circuit)
        job = self.job_of(circuit, JobQueue.LOW)

        status = self.status_of(circuit)
        self.assertEqual(status.state, MorphologyPackState.BUILDING)
        self.assertEqual(status.queue_position, 0)

        get_queue(JobQueue.LOW).remove(job)
        job.set_status(JobStatus.STARTED)
        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.BUILDING)

        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_a_job_moved_to_the_larger_queue_is_building(self):
        circuit = circuit_of(100)
        self.status_of(circuit)
        self.job_of(circuit, JobQueue.LOW).set_status(JobStatus.FINISHED)
        enqueue_build(
            JobQueue.CPU4_MEM16,
            epoch=self.epoch(),
            circuit_id=circuit.id,
            access_token="token",
            project_context=self.project_context,
        )

        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.BUILDING)
        self.assertEqual(self.job_of(circuit, JobQueue.LOW).get_status(), JobStatus.FINISHED)

    def test_a_finished_job_without_a_pack_is_queued_again(self):
        circuit = circuit_of(100)
        self.status_of(circuit)
        job = self.job_of(circuit, JobQueue.LOW)
        get_queue(JobQueue.LOW).remove(job)
        job.set_status(JobStatus.FINISHED)

        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.BUILDING)
        self.assertEqual(self.job_of(circuit, JobQueue.LOW).get_status(), JobStatus.QUEUED)

    def test_a_dead_build_is_retried_once_then_failed_for_a_day(self):
        circuit = circuit_of(100)
        self.status_of(circuit)
        job = self.job_of(circuit, JobQueue.LOW)
        directory = self.pack_dir_of(circuit.id)

        # Its worker died: the started registry still lists it, its heartbeat over
        (directory / DIR_LOCK_FILE_NAME).touch()
        (directory / f"{PACK_FILE_NAME}.{job.id}.tmp").write_bytes(b"part")
        self.abandon(job)

        status = self.status_of(circuit)

        self.assertEqual(status.state, MorphologyPackState.BUILDING)
        self.assertEqual(list(directory.iterdir()), [])
        job = self.job_of(circuit, JobQueue.LOW)
        self.assertEqual(job.get_status(), JobStatus.QUEUED)
        self.assertEqual(job.retries_left, 0)

        # The retry dies too
        self.abandon(job)

        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.FAILED)
        job = self.job_of(circuit, JobQueue.LOW)
        self.assertEqual(job.get_status(), JobStatus.FAILED)
        self.assertAlmostEqual(self.redis.ttl(job.key), FAILED_BUILD_TTL, delta=5)
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.FAILED)

        # A day later, the failed job has expired
        self.redis.delete(job.key)

        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.BUILDING)
        self.assertEqual(self.job_of(circuit, JobQueue.LOW).retries_left, 1)

    def test_the_registry_is_cleaned_up_once_in_a_while(self):
        circuit = circuit_of(100)
        self.status_of(circuit)
        job = self.job_of(circuit, JobQueue.LOW)
        self.abandon(job)

        with patch.object(
            storage, "remove_build_leftovers", wraps=storage.remove_build_leftovers
        ) as callback:
            with ThreadPoolExecutor(4) as pool:
                for future in [pool.submit(storage.clean_up_abandoned_builds) for _ in range(4)]:
                    future.result()

        callback.assert_called_once()
        self.assertEqual(self.job_of(circuit, JobQueue.LOW).retries_left, 0)
        self.assertEqual(self.queued_ids(JobQueue.LOW), [job.id])

    def test_a_failing_callback_of_another_job_on_the_queue_does_not_fail_the_request(self):
        simulation = get_queue(JobQueue.LOW).enqueue(
            "builtins.len", "x", on_failure=Callback(failing_callback)
        )
        self.abandon(simulation)

        status = self.status_of(circuit_of(100))

        self.assertEqual(status.state, MorphologyPackState.BUILDING)

    def test_no_job_while_another_request_is_queueing_it(self):
        circuit = circuit_of(100)
        job_id = build_job_id(self.epoch(), circuit.id, JobQueue.LOW)
        self.redis.set(f"morphology-pack:enqueue:{job_id}", 1)

        self.assertEqual(self.status_of(circuit).state, MorphologyPackState.BUILDING)
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

        self.redis.delete(f"morphology-pack:enqueue:{job_id}")
        self.status_of(circuit)

        self.assertEqual(self.queued_ids(JobQueue.LOW), [job_id])
        self.assertIsNone(self.redis.get(f"morphology-pack:enqueue:{job_id}"))

    def test_the_epoch_is_read_on_each_request_and_no_directory_is_created(self):
        circuit = circuit_of(100)
        self.status_of(circuit)
        first = self.epoch()

        rotate_epoch(CacheKind.MORPHOLOGY_PACK)
        self.status_of(circuit)

        self.assertNotEqual(self.epoch(), first)
        self.assertEqual(
            set(self.queued_ids(JobQueue.LOW)),
            {
                build_job_id(first, circuit.id, JobQueue.LOW),
                build_job_id(self.epoch(), circuit.id, JobQueue.LOW),
            },
        )
        self.assertEqual(list(self.storage.iterdir()), [])

    def test_the_failure_callback_imports_nothing_of_the_worker(self):
        worker_only = ["filelock", "numpy", "morphio", "obi_one", "psutil", "libsonata"]
        script = (
            "import sys; import app.infrastructure.storage.morphology_pack; "
            f"print([m for m in {worker_only} if m in sys.modules])"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        )

        self.assertEqual(result.stdout.strip(), "[]")


def _http_error(status: HTTPStatus) -> EntitySDKError:
    request = httpx.Request("GET", "https://entitycore/circuit")
    response = httpx.Response(status, request=request)
    try:
        raise httpx.HTTPStatusError("error", request=request, response=response)
    except httpx.HTTPStatusError as cause:
        try:
            raise EntitySDKError("HTTP error") from cause
        except EntitySDKError as error:
            return error


class TestCircuitAccess(MorphologyPackTestCase):
    def test_a_circuit_the_user_cannot_see_is_not_found(self):
        for status in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND]:
            with self.subTest(status=status):
                with patch.object(service, "Client") as client:
                    client.return_value.get_entity.side_effect = _http_error(status)
                    with self.assertRaises(AppError) as raised:
                        service._get_circuit(
                            uuid4(), auth=MagicMock(), project_context=self.project_context
                        )

                self.assertEqual(raised.exception.http_status_code, HTTPStatus.NOT_FOUND)

    def test_other_errors_are_raised_as_they_are(self):
        with patch.object(service, "Client") as client:
            client.return_value.get_entity.side_effect = _http_error(HTTPStatus.BAD_GATEWAY)
            with self.assertRaises(EntitySDKError):
                service._get_circuit(
                    uuid4(), auth=MagicMock(), project_context=self.project_context
                )


class TestPackFile(MorphologyPackTestCase):
    def test_not_built(self):
        with self.assertRaises(AppError) as raised:
            service._pack_response(uuid4())

        self.assertEqual(raised.exception.http_status_code, HTTPStatus.NOT_FOUND)
        self.assertEqual(list(self.storage.iterdir()), [])

    def test_built(self):
        circuit_id = uuid4()
        directory = self.pack_dir_of(circuit_id)
        content = b"0123456789"
        sha256 = hashlib.sha256(content).hexdigest()
        (directory / PACK_FILE_NAME).write_bytes(content)
        write_pack_info(directory, PackInfo(size=len(content), sha256=sha256, queue="low"))

        with self.assertRaises(AppError):
            service._pack_response(circuit_id)

        (directory / READY_MARKER_FILE_NAME).touch()
        response = service._pack_response(circuit_id)

        self.assertEqual(response.path, directory / PACK_FILE_NAME)
        self.assertEqual(response.headers["etag"], f'"{sha256}"')
