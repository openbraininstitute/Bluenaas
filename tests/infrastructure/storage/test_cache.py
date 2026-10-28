import json
import os
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.config.settings import settings
from app.constants import RETIRED_MARKER_FILE_NAME, STORAGE_TRASH_DIR_NAME
from app.infrastructure.storage import cache
from app.infrastructure.storage.cache import (
    RetiredMarker,
    cleanup_lock,
    enqueue_reclaim,
    has_unfinished_cleanup,
    reclaim_retired_roots,
    retired_roots,
    stamp_retired_roots,
)
from app.context import cid_var
from app.infrastructure.rq import JobQueue, _queues
from app.infrastructure.storage.epoch import CacheKind, current_epoch, epoch_dir_name
from app.job import JobFn
from tests.infrastructure.storage.fake_redis import FakeRedisTestCase

EXCLUDED_FUNCS = frozenset({"app.some.cleanup"})
OLD_EPOCH = "a" * 32
OLDER_EPOCH = "b" * 32


def stamp(kind: CacheKind, previous_epoch: str | None = None) -> dict:
    return stamp_retired_roots(kind, previous_epoch, exclude_func_names=EXCLUDED_FUNCS)


class CacheTestCase(FakeRedisTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Path(self._tmp.name)

        patcher = patch.object(settings, "STORAGE_PATH", self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_root(self, kind: CacheKind, name: str) -> Path:
        root = self.storage / kind.value / name
        entry = root / "model" / "a" / "b" / "entry"
        entry.mkdir(parents=True)
        (entry / "data.bin").write_bytes(b"data")
        return root

    def make_epoch_root(self, kind: CacheKind, epoch: str) -> Path:
        return self.make_root(kind, epoch_dir_name(epoch))

    def current_root(self, kind: CacheKind) -> Path:
        return self.make_epoch_root(kind, current_epoch(kind))

    def mark(
        self,
        root: Path,
        *,
        age: float = 0,
        blocking: tuple[str, ...] = (),
        trusted: bool = True,
    ) -> None:
        cache._write_marker(root, RetiredMarker(time.time() - age, blocking, trusted))

    def trash_content(self, kind: CacheKind) -> list[Path]:
        trash = self.storage / STORAGE_TRASH_DIR_NAME / kind.value
        return list(trash.iterdir()) if trash.exists() else []


class TestRetiredRoots(CacheTestCase):
    def test_every_directory_but_the_current_epoch_is_retired(self):
        current = self.current_root(CacheKind.CIRCUIT)
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        legacy = self.make_root(CacheKind.CIRCUIT, "simulation")

        self.assertCountEqual(retired_roots(CacheKind.CIRCUIT), [old, legacy])
        self.assertNotIn(current, retired_roots(CacheKind.CIRCUIT))

    def test_everything_is_retired_when_there_is_no_current_epoch(self):
        old = self.make_epoch_root(CacheKind.MESH, OLD_EPOCH)

        self.assertEqual(retired_roots(CacheKind.MESH), [old])

    def test_other_kinds_files_and_missing_cache_are_ignored(self):
        self.make_epoch_root(CacheKind.MESH, OLD_EPOCH)
        (self.storage / "circuit").mkdir()
        (self.storage / "circuit" / "stray-file").touch()

        self.assertEqual(retired_roots(CacheKind.CIRCUIT), [])
        self.assertEqual(retired_roots(CacheKind.TASK_CONFIG), [])

    def test_the_ion_channel_builds_are_retired_task_config_runs(self):
        # Where the ion channel builds were kept before they became task config runs
        builds = self.storage / "ion-channel"
        (builds / "build" / "a").mkdir(parents=True)
        current = self.current_root(CacheKind.TASK_CONFIG)

        self.assertEqual(retired_roots(CacheKind.TASK_CONFIG), [builds])
        self.assertNotIn(current, retired_roots(CacheKind.TASK_CONFIG))
        self.assertEqual(retired_roots(CacheKind.CIRCUIT), [])

    def test_the_compilation_cache_from_before_the_epochs_is_retired(self):
        # Kept under another name before the epochs
        former = self.storage / "compilation-cache"
        (former / "ab" / "cd" / "ef").mkdir(parents=True)
        current = self.current_root(CacheKind.COMPILATION)

        self.assertEqual(retired_roots(CacheKind.COMPILATION), [former])
        self.assertNotIn(current, retired_roots(CacheKind.COMPILATION))


class TestHasUnfinishedCleanup(CacheTestCase):
    def test_marked_retired_roots_and_trash_are_left_by_a_cleanup(self):
        self.current_root(CacheKind.CIRCUIT)
        self.assertFalse(has_unfinished_cleanup(CacheKind.CIRCUIT))

        (self.storage / STORAGE_TRASH_DIR_NAME / "circuit").mkdir(parents=True)
        self.assertFalse(has_unfinished_cleanup(CacheKind.CIRCUIT))

        (self.storage / STORAGE_TRASH_DIR_NAME / "circuit" / "half-deleted").mkdir()
        self.assertTrue(has_unfinished_cleanup(CacheKind.CIRCUIT))

        old = self.make_epoch_root(CacheKind.MESH, OLD_EPOCH)
        self.assertFalse(has_unfinished_cleanup(CacheKind.MESH))
        self.mark(old)
        self.assertTrue(has_unfinished_cleanup(CacheKind.MESH))

    def test_the_layout_from_before_the_epochs_is_not_left_by_a_cleanup(self):
        # No cleanup has run yet, and old workers may still use it during a deploy
        self.make_root(CacheKind.CIRCUIT, "model")
        (self.storage / "ion-channel" / "build").mkdir(parents=True)

        self.assertFalse(has_unfinished_cleanup(CacheKind.CIRCUIT))
        self.assertFalse(has_unfinished_cleanup(CacheKind.TASK_CONFIG))


class TestStampRetiredRoots(CacheTestCase):
    def test_marks_retired_roots_with_the_jobs_that_are_running(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        current = self.current_root(CacheKind.CIRCUIT)

        with patch.object(cache, "get_started_job_ids", return_value={"job-b", "job-a"}) as jobs:
            stamp(CacheKind.CIRCUIT)

        marker = cache._read_marker(old)
        assert marker is not None
        self.assertEqual(marker.blocking_job_ids, ("job-a", "job-b"))
        self.assertAlmostEqual(marker.retired_at, time.time(), delta=5)
        self.assertIsNone(cache._read_marker(current))
        # Cleanups wait for other jobs, they must never wait for each other
        jobs.assert_called_once_with(exclude_func_names=EXCLUDED_FUNCS)

    def test_roots_that_are_already_marked_keep_their_marker(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old, age=100, blocking=("early-job",))

        with patch.object(cache, "get_started_job_ids") as jobs:
            stamp(CacheKind.CIRCUIT)

        jobs.assert_not_called()
        marker = cache._read_marker(old)
        assert marker is not None
        self.assertEqual(marker.blocking_job_ids, ("early-job",))

    def test_an_unreadable_marker_is_replaced(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        (old / RETIRED_MARKER_FILE_NAME).write_text("{not json")

        with patch.object(cache, "get_started_job_ids", return_value={"job-a"}):
            stamp(CacheKind.CIRCUIT)

        marker = cache._read_marker(old)
        assert marker is not None
        self.assertEqual(marker.blocking_job_ids, ("job-a",))

    def test_the_epoch_this_cleanup_retired_is_trusted(self):
        previous = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)

        with patch.object(cache, "get_started_job_ids", return_value=set()):
            stamp(CacheKind.CIRCUIT, OLD_EPOCH)

        self.assertTrue(cache._read_marker(previous).trusted)

    def test_the_layout_from_before_the_epochs_is_not_trusted(self):
        # Workers of the previous version still start jobs on it during a deploy
        legacy = self.make_root(CacheKind.CIRCUIT, "model")
        former = self.storage / "compilation-cache"
        former.mkdir()

        with patch.object(cache, "get_started_job_ids", return_value=set()):
            stamp(CacheKind.CIRCUIT, OLD_EPOCH)
            stamp(CacheKind.COMPILATION, OLD_EPOCH)

        self.assertFalse(cache._read_marker(legacy).trusted)
        self.assertFalse(cache._read_marker(former).trusted)

    def test_an_epoch_the_cleanup_did_not_retire_is_not_trusted(self):
        # Left by a cleanup that stopped before marking it, or by Redis losing its data. The jobs
        # running now are not known to include all that use it.
        orphan = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        previous = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)

        with patch.object(cache, "get_started_job_ids", return_value=set()):
            stamp(CacheKind.CIRCUIT, OLD_EPOCH)

        self.assertFalse(cache._read_marker(orphan).trusted)
        self.assertTrue(cache._read_marker(previous).trusted)

    def test_without_a_known_previous_epoch_no_epoch_is_trusted(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)

        with patch.object(cache, "get_started_job_ids", return_value=set()):
            stamp(CacheKind.CIRCUIT)

        self.assertFalse(cache._read_marker(old).trusted)

    def test_the_previous_epoch_is_marked_before_its_jobs_create_it(self):
        # A job took the epoch just before the cleanup started a new one, and has not created
        # its directory yet
        with patch.object(cache, "get_started_job_ids", return_value={"slow-job"}):
            stamp(CacheKind.CIRCUIT, OLD_EPOCH)

        previous = self.storage / "circuit" / epoch_dir_name(OLD_EPOCH)
        marker = cache._read_marker(previous)
        assert marker is not None
        self.assertTrue(marker.trusted)
        self.assertEqual(marker.blocking_job_ids, ("slow-job",))

    def test_the_previous_epoch_is_trusted_once_known_even_if_marked_before(self):
        # Marked by a check that did not know which epoch the cleanup retired
        previous = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(previous, age=100, blocking=("early-job",), trusted=False)
        orphan = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        self.mark(orphan, age=100, trusted=False)

        with patch.object(cache, "get_started_job_ids", return_value={"job-a"}):
            stamp(CacheKind.CIRCUIT, OLD_EPOCH)

        marker = cache._read_marker(previous)
        assert marker is not None
        self.assertTrue(marker.trusted)
        self.assertEqual(marker.blocking_job_ids, ("job-a",))
        # Still deleted by its age from when it was first seen as retired
        self.assertAlmostEqual(marker.retired_at, time.time() - 100, delta=5)
        self.assertFalse(cache._read_marker(orphan).trusted)

    def test_returns_the_markers_of_all_retired_roots(self):
        marked = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        self.mark(marked, blocking=("early-job",))
        unmarked = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.current_root(CacheKind.CIRCUIT)

        with patch.object(cache, "get_started_job_ids", return_value={"job-a"}):
            markers = stamp(CacheKind.CIRCUIT)

        self.assertEqual(
            markers, {marked: cache._read_marker(marked), unmarked: cache._read_marker(unmarked)}
        )

    def test_marker_is_written_whole(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)

        with patch.object(cache, "get_started_job_ids", return_value=set()):
            stamp(CacheKind.CIRCUIT)

        data = json.loads((old / RETIRED_MARKER_FILE_NAME).read_text())
        self.assertEqual(data["blocking_job_ids"], [])
        self.assertEqual([p.name for p in old.glob("*.tmp")], [])


class TestReclaimRetiredRoots(CacheTestCase):
    def test_deletes_a_retired_root_when_its_jobs_have_finished(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old, blocking=("job-a",))

        with patch.object(cache, "get_unfinished_job_ids", return_value=set()) as unfinished:
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        unfinished.assert_called_once_with({"job-a"})
        self.assertEqual((result.reclaimed, result.pending), (1, 0))
        self.assertFalse(old.exists())
        self.assertEqual(self.trash_content(CacheKind.CIRCUIT), [])

    def test_uses_the_markers_it_is_given_instead_of_reading_them_again(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        markers = {old: RetiredMarker(time.time(), ("job-a",))}

        with (
            patch.object(cache, "_read_marker") as read_marker,
            patch.object(cache, "get_unfinished_job_ids", return_value=set()) as unfinished,
        ):
            result = reclaim_retired_roots(CacheKind.CIRCUIT, markers)

        read_marker.assert_not_called()
        unfinished.assert_called_once_with({"job-a"})
        self.assertEqual(result.reclaimed, 1)
        self.assertFalse(old.exists())

    def test_without_the_stamp_only_marked_roots_are_deleted(self):
        legacy = self.make_root(CacheKind.CIRCUIT, "model")
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old)

        with patch.object(cache, "get_unfinished_job_ids", return_value=set()):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (1, 1))
        self.assertFalse(old.exists())
        self.assertTrue(legacy.exists())

    def test_the_ion_channel_builds_are_deleted_with_the_task_config_runs_by_age(self):
        builds = self.storage / "ion-channel"
        (builds / "build" / "a").mkdir(parents=True)

        with (
            patch.object(cache, "get_started_job_ids", return_value=set()),
            patch.object(cache, "get_unfinished_job_ids", return_value=set()),
        ):
            markers = stamp(CacheKind.TASK_CONFIG)
            kept = reclaim_retired_roots(CacheKind.TASK_CONFIG, markers)
            with patch.object(settings, "CACHE_RETIRED_MAX_AGE", 0):
                deleted = reclaim_retired_roots(CacheKind.TASK_CONFIG, markers)

        self.assertEqual((kept.reclaimed, kept.pending), (0, 1))
        self.assertEqual((deleted.reclaimed, deleted.pending), (1, 0))
        self.assertFalse(builds.exists())

    def test_keeps_a_retired_root_while_a_job_that_might_use_it_runs(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old, blocking=("job-a", "job-b"))

        with patch.object(cache, "get_unfinished_job_ids", return_value={"job-b"}):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (0, 1))
        self.assertTrue((old / "model" / "a" / "b" / "entry" / "data.bin").exists())

    def test_deletes_the_root_once_it_is_older_than_any_job_can_run(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old, age=settings.CACHE_RETIRED_MAX_AGE + 1, blocking=("ghost-job",))

        with patch.object(cache, "get_unfinished_job_ids", return_value={"ghost-job"}):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual(result.reclaimed, 1)
        self.assertFalse(old.exists())

    def test_an_untrusted_root_is_kept_even_when_no_job_is_running(self):
        # Pre-flush jobs that still use it are invisible to the job registry
        orphan = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        cache._write_marker(orphan, RetiredMarker(time.time(), (), trusted=False))

        with patch.object(cache, "get_unfinished_job_ids", return_value=set()):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (0, 1))
        self.assertTrue(orphan.exists())

    def test_an_untrusted_root_is_deleted_once_it_is_old_enough(self):
        orphan = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        cache._write_marker(
            orphan,
            RetiredMarker(time.time() - settings.CACHE_RETIRED_MAX_AGE - 1, (), trusted=False),
        )

        with patch.object(cache, "get_unfinished_job_ids", return_value=set()):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual(result.reclaimed, 1)
        self.assertFalse(orphan.exists())

    def test_keeps_a_root_that_is_not_marked_yet(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)

        result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (0, 1))
        self.assertTrue(old.exists())

    def test_never_touches_the_current_epoch(self):
        current = self.current_root(CacheKind.CIRCUIT)
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old)

        with patch.object(cache, "get_unfinished_job_ids", return_value=set()):
            reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertTrue(current.exists())
        self.assertFalse(old.exists())

    def test_does_not_touch_other_cache_kinds(self):
        mesh = self.make_epoch_root(CacheKind.MESH, OLDER_EPOCH)
        self.mark(mesh)
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old)

        with patch.object(cache, "get_unfinished_job_ids", return_value=set()):
            reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertTrue(mesh.exists())

    def test_reclaims_each_retired_root_on_its_own_terms(self):
        done = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(done, blocking=("finished-job",))
        busy = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        self.mark(busy, blocking=("running-job",))
        legacy = self.make_root(CacheKind.CIRCUIT, "model")
        self.mark(legacy, blocking=("finished-job",))

        with patch.object(
            cache,
            "get_unfinished_job_ids",
            side_effect=lambda ids: {i for i in ids if i == "running-job"},
        ):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (2, 1))
        self.assertFalse(done.exists())
        self.assertFalse(legacy.exists())
        self.assertTrue(busy.exists())

    def test_leftovers_of_an_interrupted_cleanup_are_deleted(self):
        leftover = self.storage / STORAGE_TRASH_DIR_NAME / "circuit" / "interrupted" / "a" / "b"
        leftover.mkdir(parents=True)
        (leftover / "data.bin").write_bytes(b"data")

        reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual(self.trash_content(CacheKind.CIRCUIT), [])

    def test_a_root_that_could_not_be_fully_deleted_is_pending(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old)

        with (
            patch.object(cache, "get_unfinished_job_ids", return_value=set()),
            patch.object(cache, "rm_dir_parallel"),
        ):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (0, 1))
        self.assertFalse(old.exists())
        self.assertEqual(len(self.trash_content(CacheKind.CIRCUIT)), 1)

        # The next check deletes what was left
        result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (0, 0))
        self.assertEqual(self.trash_content(CacheKind.CIRCUIT), [])

    def test_leftovers_that_cannot_be_deleted_are_pending(self):
        leftover = self.storage / STORAGE_TRASH_DIR_NAME / "circuit" / "interrupted"
        leftover.mkdir(parents=True)

        with patch.object(cache, "rm_dir_parallel"):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual(result.pending, 1)

    def test_a_root_that_someone_else_deleted_in_the_meantime_is_skipped(self):
        old = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(old)

        with (
            patch.object(cache, "get_unfinished_job_ids", return_value=set()),
            patch.object(cache.os, "rename", side_effect=FileNotFoundError),
        ):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (0, 0))

    def test_a_root_that_cannot_be_moved_is_left_for_the_next_attempt(self):
        stuck = self.make_epoch_root(CacheKind.CIRCUIT, OLD_EPOCH)
        self.mark(stuck)
        other = self.make_epoch_root(CacheKind.CIRCUIT, OLDER_EPOCH)
        self.mark(other)
        original_rename = os.rename

        def rename_unless_stuck(src, dst):
            if Path(src) == stuck:
                raise PermissionError(src)
            return original_rename(src, dst)

        with (
            patch.object(cache, "get_unfinished_job_ids", return_value=set()),
            patch.object(cache.os, "rename", side_effect=rename_unless_stuck),
        ):
            result = reclaim_retired_roots(CacheKind.CIRCUIT)

        self.assertEqual((result.reclaimed, result.pending), (1, 1))
        self.assertTrue(stuck.exists())
        self.assertFalse(other.exists())


class TestEnqueueReclaim(unittest.TestCase):
    def setUp(self):
        self.queue = MagicMock()
        patcher = patch.dict(_queues, {JobQueue.MEDIUM: self.queue})
        patcher.start()
        self.addCleanup(patcher.stop)
        token = cid_var.set("request-cid")
        self.addCleanup(cid_var.reset, token)

    def test_queued_right_away_by_default(self):
        enqueue_reclaim(CacheKind.MESH, previous_epoch=OLD_EPOCH)

        self.queue.enqueue_in.assert_not_called()
        args, kwargs = self.queue.enqueue.call_args
        self.assertEqual(args, (JobFn.RECLAIM_RETIRED_CACHE, "mesh", 1, OLD_EPOCH))
        self.assertEqual(kwargs["meta"], {"cid": "request-cid"})
        self.assertTrue(kwargs["follow_up"])
        self.assertTrue(kwargs["mark"])

    def test_scheduled_with_a_delay(self):
        enqueue_reclaim(CacheKind.MESH, attempt=3, delay_seconds=300, follow_up=False)

        self.queue.enqueue.assert_not_called()
        args, kwargs = self.queue.enqueue_in.call_args
        self.assertEqual(
            args, (timedelta(seconds=300), JobFn.RECLAIM_RETIRED_CACHE, "mesh", 3, None)
        )
        self.assertFalse(kwargs["follow_up"])


class TestCleanupLock(FakeRedisTestCase):
    def test_only_one_cleanup_of_a_kind_at_a_time(self):
        with cleanup_lock(CacheKind.CIRCUIT) as first:
            with cleanup_lock(CacheKind.CIRCUIT) as second:
                with cleanup_lock(CacheKind.MESH) as other_kind:
                    pass

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(other_kind)

    def test_lock_is_released_afterwards_and_after_an_error(self):
        with self.assertRaises(RuntimeError):
            with cleanup_lock(CacheKind.CIRCUIT):
                raise RuntimeError

        with cleanup_lock(CacheKind.CIRCUIT) as acquired:
            self.assertTrue(acquired)

    def test_an_expired_lock_is_not_an_error(self):
        with cleanup_lock(CacheKind.CIRCUIT):
            self.redis.held_locks.clear()

    def test_the_lock_is_short_and_renewed_while_the_cleanup_runs(self):
        # A cleanup that was killed does not hold up the next ones for long
        with patch.object(cache, "CACHE_CLEANUP_LOCK_TTL", 0.03):
            with cleanup_lock(CacheKind.CIRCUIT):
                time.sleep(0.1)
            (lock,) = self.redis.locks
            renewals = len(lock.extensions)
            time.sleep(0.05)

        self.assertEqual(lock.timeout, 0.03)
        self.assertGreater(renewals, 0)
        self.assertEqual(lock.extensions[0], (0.03, True))
        # Not renewed after the release
        self.assertEqual(len(lock.extensions), renewals)

    def test_the_renewal_stops_once_the_lock_is_lost(self):
        with patch.object(cache, "CACHE_CLEANUP_LOCK_TTL", 0.03):
            with cleanup_lock(CacheKind.CIRCUIT):
                self.redis.held_locks.clear()
                time.sleep(0.1)

        (lock,) = self.redis.locks
        self.assertEqual(lock.extensions, [])


if __name__ == "__main__":
    unittest.main()
