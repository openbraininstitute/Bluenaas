"""The tiny part of Redis that the cache epochs and the cleanup lock use."""

import os
import unittest
from unittest.mock import patch

from redis.exceptions import LockError


class _Pipeline:
    def __init__(self, redis: "FakeRedis"):
        self._redis = redis
        self._commands: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, key):
        self._commands.append(lambda: self._redis.get(key))

    def set(self, key, value, **kwargs):
        self._commands.append(lambda: self._redis.set(key, value, **kwargs))

    def execute(self):
        return [command() for command in self._commands]


class _Lock:
    def __init__(self, redis: "FakeRedis", name: str):
        self._redis = redis
        self._name = name

    def acquire(self) -> bool:
        if self._name in self._redis.held_locks:
            return False
        self._redis.held_locks.add(self._name)
        return True

    def release(self) -> None:
        if self._name not in self._redis.held_locks:
            raise LockError("Cannot release an unlocked lock")
        self._redis.held_locks.discard(self._name)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, bytes] = {}
        self.held_locks: set[str] = set()

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value.encode() if isinstance(value, str) else value
        return True

    def pipeline(self, transaction=True):
        return _Pipeline(self)

    def lock(self, name, timeout=None, blocking=True):
        return _Lock(self, name)


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

        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in [n for n in os.environ if n.startswith("CACHE_EPOCH_")]:
            del os.environ[name]
