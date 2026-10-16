import os
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

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
        self.calls: list[str] = []

        def record(name, result=None):
            def fn(*args, **kwargs):
                self.calls.append(name)
                return result

            return fn

        self.reclaim_result = ReclaimResult(reclaimed=1, pending=0)
        patches = {
            "rotate_epoch": record("rotate", "previous"),
            "stamp_retired_roots": record("stamp"),
            "reclaim_retired_roots": lambda *a, **k: (
                self.calls.append("reclaim") or self.reclaim_result
            ),
        }
        for name, fn in patches.items():
            patcher = patch.object(service, name, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

        sleep = patch.object(
            service.time, "sleep", side_effect=lambda s: self.calls.append("sleep")
        )
        sleep.start()
        self.addCleanup(sleep.stop)

        self.queue = MagicMock()
        queue = patch.object(service, "get_queue", return_value=self.queue)
        queue.start()
        self.addCleanup(queue.stop)


class TestClearCache(ServiceTestCase):
    def test_starts_a_new_epoch_waits_and_reclaims_in_that_order(self):
        result = service.clear_cache(CacheKind.CIRCUIT)

        self.assertEqual(self.calls, ["rotate", "sleep", "stamp", "reclaim"])
        # The epoch this cleanup retired is the one whose job list can be trusted
        service.stamp_retired_roots.assert_called_once_with(CacheKind.CIRCUIT, "previous")
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
        self.assertEqual(self.calls, [])
        self.queue.enqueue_in.assert_not_called()

    def test_the_lock_is_released_when_the_cleanup_fails(self):
        with patch.object(service, "stamp_retired_roots", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service.clear_cache(CacheKind.MESH)

        self.assertEqual(self.redis.held_locks, set())


class TestReclaimRetiredCache(ServiceTestCase):
    def test_reclaims_without_starting_a_new_epoch(self):
        result = service.reclaim_retired_cache(CacheKind.CIRCUIT, attempt=3)

        self.assertEqual(self.calls, ["stamp", "reclaim"])
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
        self.assertEqual(self.calls, [])
        self.queue.enqueue_in.assert_not_called()


if __name__ == "__main__":
    unittest.main()
