"""The tiny part of Redis that the cache epochs and the cleanup lock use."""

import os
import unittest
from unittest.mock import patch

from redis.exceptions import LockError, LockNotOwnedError

from app.infrastructure.storage.epoch import PINNED_EPOCH_ENV_PREFIX


class _Lock:
    def __init__(self, redis: "FakeRedis", name: str, timeout):
        self._redis = redis
        self._name = name
        self.timeout = timeout
        self.extensions: list = []

    def acquire(self) -> bool:
        if self._name in self._redis.held_locks:
            return False
        self._redis.held_locks.add(self._name)
        return True

    def release(self) -> None:
        if self._name not in self._redis.held_locks:
            raise LockError("Cannot release an unlocked lock")
        self._redis.held_locks.discard(self._name)

    def extend(self, additional_time, replace_ttl=False):
        if self._name not in self._redis.held_locks:
            raise LockNotOwnedError("Cannot extend a lock that's no longer owned")
        self.extensions.append((additional_time, replace_ttl))
        return True


class FakeRedis:
    def __init__(self):
        self.data: dict[str, bytes] = {}
        self.held_locks: set[str] = set()
        self.locks: list[_Lock] = []

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, nx=False, ex=None, get=False):
        previous = self.data.get(key)
        if nx and previous is not None:
            return None
        self.data[key] = value.encode() if isinstance(value, str) else value
        return previous if get else True

    def delete(self, *keys):
        return sum(self.data.pop(key, None) is not None for key in keys)

    def lock(self, name, timeout=None, blocking=True, thread_local=True):
        lock = _Lock(self, name, timeout)
        self.locks.append(lock)
        return lock


class FakeRedisTestCase(unittest.TestCase):
    """Runs the test with an in-memory Redis and no cache epoch fixed by the test process."""

    def setUp(self):
        self.redis = FakeRedis()
        for target in (
            "app.infrastructure.storage.epoch.redis_client",
            "app.infrastructure.storage.cache.redis_client",
        ):
            patcher = patch(target, self.redis)
            patcher.start()
            self.addCleanup(patcher.stop)

        self._forget_pinned_epochs()

    def _forget_pinned_epochs(self):
        # Not patch.dict(os.environ): it clears and refills the whole environment, and NEURON,
        # once imported, can no longer load its hoc files after that.
        saved = {n: v for n, v in os.environ.items() if n.startswith(PINNED_EPOCH_ENV_PREFIX)}
        for name in saved:
            del os.environ[name]

        def restore():
            for name in [n for n in os.environ if n.startswith(PINNED_EPOCH_ENV_PREFIX)]:
                del os.environ[name]
            os.environ.update(saved)

        self.addCleanup(restore)
