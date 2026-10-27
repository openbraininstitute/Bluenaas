import os
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.config.settings import settings
from app.constants import CACHE_CLEANUP_TIMEOUT, CACHE_RECLAIM_MAX_ATTEMPTS
from app.infrastructure.storage import cache
from app.infrastructure.storage.cache import ReclaimResult
from app.infrastructure.storage.epoch import CacheKind
from app.job import JobFn
from app.services.worker.admin import cache as service
from tests.infrastructure.storage.fake_redis import FakeRedisTestCase

MARKERS = {Path("/storage/circuit/old"): None}


class ServiceTestCase(FakeRedisTestCase):
    def setUp(self):
        super().setUp()
        self.reclaim_result = ReclaimResult(reclaimed=1, pending=0)

        # All collaborators hang off one parent, so that the order of calls can be checked
        self.parent = MagicMock()
        self.parent.stamp_retired_roots.return_value = MARKERS
        self.parent.reclaim_retired_roots.side_effect = lambda kind, markers: self.reclaim_result

        for name, replacement in (
            ("stamp_retired_roots", self.parent.stamp_retired_roots),
            ("reclaim_retired_roots", self.parent.reclaim_retired_roots),
        ):
            patcher = patch.object(service, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.queue = MagicMock()
        for target in (service, cache):
            patcher = patch.object(target, "get_queue", return_value=self.queue)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = patch.object(service, "redis_client", self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def stamp_call(self, kind: CacheKind, previous: str | None):
        return call.stamp_retired_roots(
            kind, previous, exclude_func_names=service.CLEANUP_JOB_FUNC_NAMES
        )


class TestCleanupJobFuncNames(unittest.TestCase):
    def test_cleanup_jobs_do_not_wait_for_cleanup_jobs(self):
        self.assertEqual(service.CLEANUP_JOB_FUNC_NAMES, {JobFn.RECLAIM_RETIRED_CACHE.value})


class TestReclaimRetiredCache(ServiceTestCase):
    def test_reclaims_without_starting_a_new_epoch(self):
        result = service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=3, previous_epoch="p")

        self.assertEqual(
            self.parent.mock_calls,
            [
                self.stamp_call(CacheKind.CIRCUIT, "p"),
                # What the stamp read is not read again
                call.reclaim_retired_roots(CacheKind.CIRCUIT, MARKERS),
            ],
        )
        self.assertEqual(result, {"status": "ok", "reclaimed": 1, "pending": 0})
        self.queue.enqueue_in.assert_not_called()
        self.assertEqual(self.redis.held_locks, set())

    def test_the_epoch_to_trust_defaults_to_none(self):
        service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=1)

        self.assertEqual(self.parent.mock_calls[0], self.stamp_call(CacheKind.CIRCUIT, None))

    def test_checks_again_later_while_epochs_are_still_in_use(self):
        self.reclaim_result = ReclaimResult(pending=1)

        service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=3, previous_epoch="p")

        args, kwargs = self.queue.enqueue_in.call_args
        # The previous epoch is marked by now. Passed on, a later check would create its
        # directory again once it is deleted.
        self.assertEqual(
            args,
            (
                timedelta(seconds=settings.CACHE_RECLAIM_POLL_SECONDS),
                JobFn.RECLAIM_RETIRED_CACHE,
                "circuit",
                4,
                None,
            ),
        )
        self.assertEqual(kwargs["job_timeout"], CACHE_CLEANUP_TIMEOUT)

    def test_gives_up_after_too_many_checks(self):
        self.reclaim_result = ReclaimResult(pending=1)

        with patch.object(service, "logger") as logger:
            service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=CACHE_RECLAIM_MAX_ATTEMPTS)

        self.queue.enqueue_in.assert_not_called()
        logger.error.assert_called_once()

    def test_checks_again_later_when_another_cleanup_holds_the_lock(self):
        self.redis.held_locks.add("cache:cleanup-lock:circuit")

        result = service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=1, previous_epoch="p")

        self.assertEqual(result, {"status": "already_running"})
        self.assertEqual(self.parent.mock_calls, [])
        args, _ = self.queue.enqueue_in.call_args
        self.assertEqual(args[1:], (JobFn.RECLAIM_RETIRED_CACHE, "circuit", 2, "p"))
        # The lock belongs to the other cleanup
        self.assertEqual(self.redis.held_locks, {"cache:cleanup-lock:circuit"})

    def test_checks_again_later_and_releases_the_lock_when_the_reclaim_fails(self):
        self.parent.reclaim_retired_roots.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            service.reclaim_retired_cache(CacheKind.MESH, attempt=2, previous_epoch="p")

        self.assertEqual(self.redis.held_locks, set())
        args, _ = self.queue.enqueue_in.call_args
        self.assertEqual(args[1:], (JobFn.RECLAIM_RETIRED_CACHE, "mesh", 3, "p"))

    def test_a_failure_to_check_again_does_not_hide_the_failure_of_the_reclaim(self):
        self.parent.reclaim_retired_roots.side_effect = RuntimeError("boom")
        self.queue.enqueue_in.side_effect = ConnectionError("redis is gone")

        with patch.object(service, "logger") as logger:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                service.reclaim_retired_cache(CacheKind.MESH, attempt=2, previous_epoch="p")

        self.assertEqual(logger.exception.call_count, 2)

    def test_a_single_check_is_not_repeated(self):
        cases = {
            "pending": lambda: setattr(self, "reclaim_result", ReclaimResult(pending=1)),
            "locked": lambda: self.redis.held_locks.add("cache:cleanup-lock:circuit"),
        }
        for name, setup in cases.items():
            with self.subTest(name):
                self.redis.held_locks.clear()
                setup()

                service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=1, follow_up=False)

                self.queue.enqueue_in.assert_not_called()

        self.redis.held_locks.clear()
        self.parent.reclaim_retired_roots.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=1, follow_up=False)
        self.queue.enqueue_in.assert_not_called()


class TestReclaimWithoutMarking(ServiceTestCase):
    def test_only_deletes_what_is_marked_already(self):
        result = service.reclaim_retired_cache(
            CacheKind.CIRCUIT, attempt=1, follow_up=False, mark=False
        )

        self.assertEqual(
            self.parent.mock_calls, [call.reclaim_retired_roots(CacheKind.CIRCUIT, None)]
        )
        self.assertEqual(result["status"], "ok")


class TestStartPendingReclaims(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.leftovers = {CacheKind.CIRCUIT}
        patcher = patch.object(
            service, "has_unfinished_cleanup", side_effect=lambda kind: kind in self.leftovers
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_queues_a_single_check_of_the_caches_with_leftovers(self):
        service.start_pending_reclaims()

        self.queue.enqueue_in.assert_not_called()
        self.queue.enqueue.assert_called_once()
        args, kwargs = self.queue.enqueue.call_args
        self.assertEqual(args, (JobFn.RECLAIM_RETIRED_CACHE, "circuit", 1))
        self.assertFalse(kwargs["follow_up"])
        # Before the first cleanup, the layout from before the epochs looks retired
        self.assertFalse(kwargs["mark"])
        self.assertEqual(kwargs["job_timeout"], CACHE_CLEANUP_TIMEOUT)

    def test_only_one_of_the_workers_starting_together_queues_the_checks(self):
        service.start_pending_reclaims()
        service.start_pending_reclaims()

        self.queue.enqueue.assert_called_once()

    def test_a_failure_does_not_stop_the_worker_or_the_other_kinds(self):
        self.leftovers = {CacheKind.CIRCUIT, CacheKind.MESH}
        self.queue.enqueue.side_effect = [ConnectionError("redis is gone"), MagicMock()]

        with patch.object(service, "logger") as logger:
            service.start_pending_reclaims()

        self.assertEqual(self.queue.enqueue.call_count, 2)
        logger.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
