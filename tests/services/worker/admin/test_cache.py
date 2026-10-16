import os
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.config.settings import settings
from app.constants import CACHE_CLEANUP_TIMEOUT, CACHE_RECLAIM_MAX_ATTEMPTS
from app.infrastructure.storage.cache import ReclaimResult
from app.infrastructure.storage.epoch import CacheKind
from app.job import JobFn
from app.services.worker.admin import cache as service
from tests.infrastructure.storage.fake_redis import FakeRedisTestCase


class ServiceTestCase(FakeRedisTestCase):
    def setUp(self):
        super().setUp()
        self.reclaim_result = ReclaimResult(reclaimed=1, pending=0)

        # All collaborators hang off one parent, so that the order of calls can be checked
        self.parent = MagicMock()
        self.parent.rotate_epoch.return_value = "previous"
        self.parent.reclaim_retired_roots.side_effect = lambda kind: self.reclaim_result

        for name, replacement in (
            ("rotate_epoch", self.parent.rotate_epoch),
            ("stamp_retired_roots", self.parent.stamp_retired_roots),
            ("reclaim_retired_roots", self.parent.reclaim_retired_roots),
        ):
            patcher = patch.object(service, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.queue = MagicMock()
        queue = patch.object(service, "get_queue", return_value=self.queue)
        queue.start()
        self.addCleanup(queue.stop)

    def stamp_call(self, kind: CacheKind, previous: str | None):
        return call.stamp_retired_roots(
            kind, previous, exclude_func_names=service.CLEANUP_JOB_FUNC_NAMES
        )


class TestCleanupJobFuncNames(unittest.TestCase):
    def test_cleanup_jobs_do_not_wait_for_cleanup_jobs(self):
        self.assertEqual(
            service.CLEANUP_JOB_FUNC_NAMES,
            {JobFn.CLEAR_CACHE.value, JobFn.RECLAIM_RETIRED_CACHE.value},
        )


class TestClearCache(ServiceTestCase):
    def test_starts_a_new_epoch_and_schedules_the_reclaim_after_the_settle_time(self):
        result = service.clear_cache(CacheKind.CIRCUIT)

        self.assertEqual(self.parent.mock_calls, [call.rotate_epoch(CacheKind.CIRCUIT)])
        self.assertEqual(result, {"status": "ok", "previous_epoch": "previous"})
        self.queue.enqueue_in.assert_called_once()
        args, kwargs = self.queue.enqueue_in.call_args
        self.assertEqual(
            args,
            (
                timedelta(seconds=settings.CACHE_EPOCH_SETTLE_SECONDS),
                JobFn.RECLAIM_RETIRED_CACHE,
                "circuit",
                1,
                "previous",
            ),
        )
        self.assertEqual(kwargs["job_timeout"], CACHE_CLEANUP_TIMEOUT)

    def test_does_not_wait_for_a_running_cleanup(self):
        self.redis.held_locks.add("cache:cleanup-lock:circuit")

        result = service.clear_cache(CacheKind.CIRCUIT)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.parent.mock_calls, [call.rotate_epoch(CacheKind.CIRCUIT)])
        self.queue.enqueue_in.assert_called_once()

    def test_does_not_take_the_cleanup_lock(self):
        service.clear_cache(CacheKind.MESH)

        self.assertEqual(self.redis.held_locks, set())


class TestReclaimRetiredCache(ServiceTestCase):
    def test_reclaims_without_starting_a_new_epoch(self):
        result = service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=3, previous_epoch="p")

        self.assertEqual(
            self.parent.mock_calls,
            [
                self.stamp_call(CacheKind.CIRCUIT, "p"),
                call.reclaim_retired_roots(CacheKind.CIRCUIT),
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
        self.assertEqual(
            args,
            (
                timedelta(seconds=settings.CACHE_RECLAIM_POLL_SECONDS),
                JobFn.RECLAIM_RETIRED_CACHE,
                "circuit",
                4,
                "p",
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


if __name__ == "__main__":
    unittest.main()
