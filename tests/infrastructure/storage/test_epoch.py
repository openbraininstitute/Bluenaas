import os
import subprocess
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.infrastructure.storage.epoch import (
    CacheKind,
    clear_pinned_epochs,
    current_epoch,
    epoch_dir_name,
    get_epoch,
    is_epoch_dir_name,
    rotate_epoch,
)
from tests.infrastructure.storage.fake_redis import FakeRedisTestCase


class TestCurrentEpoch(FakeRedisTestCase):
    def test_first_use_creates_the_epoch_and_later_uses_get_the_same_one(self):
        self.assertIsNone(get_epoch(CacheKind.CIRCUIT))

        epoch = current_epoch(CacheKind.CIRCUIT)

        self.assertEqual(get_epoch(CacheKind.CIRCUIT), epoch)
        self.assertEqual(current_epoch(CacheKind.CIRCUIT), epoch)

    def test_epochs_are_per_kind(self):
        self.assertNotEqual(current_epoch(CacheKind.CIRCUIT), current_epoch(CacheKind.MESH))

    def test_the_epoch_of_a_running_job_does_not_change_when_a_cleanup_starts_a_new_one(self):
        epoch = current_epoch(CacheKind.CIRCUIT)

        rotate_epoch(CacheKind.CIRCUIT)

        self.assertNotEqual(get_epoch(CacheKind.CIRCUIT), epoch)
        self.assertEqual(current_epoch(CacheKind.CIRCUIT), epoch)

    def test_the_next_job_gets_the_new_epoch(self):
        old = current_epoch(CacheKind.CIRCUIT)
        rotate_epoch(CacheKind.CIRCUIT)

        clear_pinned_epochs()

        self.assertNotEqual(current_epoch(CacheKind.CIRCUIT), old)

    def test_processes_started_by_the_job_get_its_epoch(self):
        epoch = current_epoch(CacheKind.SINGLE_NEURON)
        rotate_epoch(CacheKind.SINGLE_NEURON)

        child = subprocess.run(
            [sys.executable, "-c", "import os; print(os.environ['PINNED_CACHE_EPOCH_SINGLE_NEURON'])"],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(child.stdout.strip(), epoch)

    def test_clear_pinned_epochs_leaves_the_settings_alone(self):
        os.environ["CACHE_EPOCH_SETTLE_SECONDS"] = "5"
        self.addCleanup(os.environ.pop, "CACHE_EPOCH_SETTLE_SECONDS", None)

        clear_pinned_epochs()

        self.assertEqual(os.environ["CACHE_EPOCH_SETTLE_SECONDS"], "5")

    def test_fails_loudly_when_the_epoch_cannot_be_read_back(self):
        with patch.object(self.redis, "get", return_value=None):
            with self.assertRaises(RuntimeError):
                current_epoch(CacheKind.CIRCUIT)

    def test_clear_pinned_epochs_only_touches_epochs(self):
        current_epoch(CacheKind.CIRCUIT)
        os.environ["SOMETHING_ELSE"] = "kept"
        self.addCleanup(os.environ.pop, "SOMETHING_ELSE", None)

        clear_pinned_epochs()

        self.assertNotIn("PINNED_CACHE_EPOCH_CIRCUIT", os.environ)
        self.assertEqual(os.environ["SOMETHING_ELSE"], "kept")


class TestRotateEpoch(FakeRedisTestCase):
    def test_returns_the_previous_epoch(self):
        epoch = current_epoch(CacheKind.MESH)

        self.assertEqual(rotate_epoch(CacheKind.MESH), epoch)

    def test_returns_none_when_there_was_no_epoch(self):
        self.assertIsNone(rotate_epoch(CacheKind.MESH))

    def test_epochs_are_never_reused(self):
        seen = {rotate_epoch(CacheKind.MESH) for _ in range(20)} | {get_epoch(CacheKind.MESH)}

        self.assertEqual(len(seen), 21)

    def test_an_epoch_is_not_reused_after_redis_loses_its_data(self):
        first = current_epoch(CacheKind.MESH)
        self.redis.data.clear()
        clear_pinned_epochs()

        self.assertNotEqual(current_epoch(CacheKind.MESH), first)


class TestEpochDirNames(unittest.TestCase):
    def test_epoch_dir_names(self):
        self.assertTrue(is_epoch_dir_name(epoch_dir_name("0123456789abcdef0123456789abcdef")))

    def test_other_names_are_not_epochs(self):
        for name in (
            "model",
            "simulation",
            "ab",
            "e123",
            ".trash",
            "E0123456789abcdef0123456789abcdef",
        ):
            with self.subTest(name=name):
                self.assertFalse(is_epoch_dir_name(name))


if __name__ == "__main__":
    unittest.main()
