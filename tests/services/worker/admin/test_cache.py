import os
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.config.settings import settings
from app.constants import CACHE_RECLAIM_MAX_ATTEMPTS
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

        sleep = patch.object(service.time, "sleep", self.parent.sleep)
        sleep.start()
        self.addCleanup(sleep.stop)

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
    def test_starts_a_new_epoch_waits_and_reclaims_in_that_order(self):
        result = service.clear_cache(CacheKind.CIRCUIT)

        self.assertEqual(
            self.parent.mock_calls,
            [
                call.rotate_epoch(CacheKind.CIRCUIT),
                call.sleep(settings.CACHE_EPOCH_SETTLE_SECONDS),
                # The epoch this cleanup retired is the one whose job list can be trusted
                self.stamp_call(CacheKind.CIRCUIT, "previous"),
                call.reclaim_retired_roots(CacheKind.CIRCUIT),
            ],
        )
        self.assertEqual(result, {"status": "ok", "reclaimed": 1, "pending": 0})
        self.queue.enqueue_in.assert_not_called()

    def test_schedules_another_check_when_epochs_are_still_in_use(self):
        self.reclaim_result = ReclaimResult(reclaimed=0, pending=2)

        result = service.clear_cache(CacheKind.CIRCUIT)

        self.assertEqual(result["pending"], 2)
        self.queue.enqueue_in.assert_called_once()
        args, kwargs = self.queue.enqueue_in.call_args
        self.assertEqual(
            args,
            (
                timedelta(seconds=settings.CACHE_RECLAIM_POLL_SECONDS),
                JobFn.RECLAIM_RETIRED_CACHE,
                "circuit",
                1,
            ),
        )
        self.assertIn("job_timeout", kwargs)

    def test_does_nothing_when_another_cleanup_of_the_kind_is_running(self):
        self.redis.held_locks.add("cache:cleanup-lock:circuit")

        result = service.clear_cache(CacheKind.CIRCUIT)

        self.assertEqual(result, {"status": "already_running"})
        self.assertEqual(self.parent.mock_calls, [])
        self.queue.enqueue_in.assert_not_called()

    def test_the_lock_is_released_when_the_cleanup_fails(self):
        with patch.object(service, "stamp_retired_roots", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service.clear_cache(CacheKind.MESH)

        self.assertEqual(self.redis.held_locks, set())


class TestReclaimRetiredCache(ServiceTestCase):
    def test_reclaims_without_starting_a_new_epoch(self):
        result = service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=3)

        self.assertEqual(
            self.parent.mock_calls,
            [
                self.stamp_call(CacheKind.CIRCUIT, None),
                call.reclaim_retired_roots(CacheKind.CIRCUIT),
            ],
        )
        self.assertEqual(result["reclaimed"], 1)
        self.queue.enqueue_in.assert_not_called()

    def test_checks_again_later_while_epochs_are_still_in_use(self):
        self.reclaim_result = ReclaimResult(pending=1)

        service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=3)

        args, _ = self.queue.enqueue_in.call_args
        self.assertEqual(args[1:], (JobFn.RECLAIM_RETIRED_CACHE, "circuit", 4))

    def test_gives_up_after_too_many_checks(self):
        self.reclaim_result = ReclaimResult(pending=1)

        with patch.object(service, "logger") as logger:
            service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=CACHE_RECLAIM_MAX_ATTEMPTS)

        self.queue.enqueue_in.assert_not_called()
        logger.error.assert_called_once()

    def test_does_nothing_when_a_cleanup_is_running(self):
        self.redis.held_locks.add("cache:cleanup-lock:circuit")

        result = service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=1)

        self.assertEqual(result, {"status": "already_running"})
        self.assertEqual(self.parent.mock_calls, [])
        self.queue.enqueue_in.assert_not_called()


if __name__ == "__main__":
    unittest.main()
