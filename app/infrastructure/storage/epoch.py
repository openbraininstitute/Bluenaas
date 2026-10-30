"""Epochs of the on-disk caches.

Every cache kind lives under `<STORAGE_PATH>/<kind>/e<epoch>/`. The current epoch of a kind is kept
in Redis, so that all the hosts agree on it at once, which a file on a network filesystem with
attribute caching cannot give.

Clearing a cache starts a new epoch. Jobs that start from then on use the new, empty directory and
the old one is never modified or removed while a job that might be using it is running. This is
what makes it safe to delete a cache that is in use, including on a network filesystem where
deleting a file under a reader on another host breaks that reader.

A job takes the epochs when it starts, once a worker has put it among the started jobs, and keeps
them, also for the processes it starts, through environment variables. A cleanup thus finds every
job that might use the epoch it retires among the started jobs, and a spawned child cannot end up
in a newer epoch than its parent.
"""

import os
import re
from enum import StrEnum
from typing import cast
from uuid import uuid4

from loguru import logger

from app.infrastructure.redis import redis_client


class CacheKind(StrEnum):
    CIRCUIT = "circuit"
    SINGLE_NEURON = "single-neuron"
    MESH = "mesh"
    TASK_CONFIG = "task-config"
    COMPILATION = "compilation"
    MORPHOLOGY_PACK = "morphology-pack"


# Not to be mistaken for a setting: the settings are read from environment variables named like
# them, and the pinned epochs are removed from the environment when a job starts.
PINNED_EPOCH_ENV_PREFIX = "PINNED_CACHE_EPOCH_"

# Epochs are random and never reused: a counter would start over after Redis loses its data and
# could point new jobs at a directory that is about to be deleted.
_EPOCH_DIR_PATTERN = re.compile(r"^e[0-9a-f]{32}$")


def _redis_key(kind: CacheKind) -> str:
    return f"cache:epoch:{kind.value}"


def _pinned_epoch_env_var(kind: CacheKind) -> str:
    return f"{PINNED_EPOCH_ENV_PREFIX}{kind.name}"


def _decode(value: bytes | str | None) -> str | None:
    # redis-py returns bytes, or str when the client decodes responses
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


def epoch_dir_name(epoch: str) -> str:
    return f"e{epoch}"


def is_epoch_dir_name(name: str) -> bool:
    return _EPOCH_DIR_PATTERN.match(name) is not None


def get_epoch(kind: CacheKind) -> str | None:
    """The current epoch, or None if the cache has never been used."""
    return _decode(redis_client.get(_redis_key(kind)))


def current_epoch(kind: CacheKind) -> str:
    """The epoch the running job uses. It is fixed on the first call and then kept."""
    env_var = _pinned_epoch_env_var(kind)

    pinned = os.environ.get(env_var)
    if pinned:
        return pinned

    epoch = ensure_epoch(kind)
    os.environ[env_var] = epoch
    return epoch


def ensure_epoch(kind: CacheKind) -> str:
    """The current epoch, started if the cache has never been used. Not fixed for the process."""
    epoch = get_epoch(kind)
    if epoch is None:
        # Whoever gets there first wins, the others use the winner's epoch
        if redis_client.set(_redis_key(kind), uuid4().hex, nx=True):
            # Expected once per kind. Any other time Redis lost the key (flush, eviction), the
            # cache goes cold and the epoch running jobs still use can only be deleted by age.
            logger.warning(
                f"Started the first {kind.value} cache epoch: either the cache is used for the "
                "first time or Redis lost the current epoch"
            )
        epoch = get_epoch(kind)
        if epoch is None:
            raise RuntimeError(f"The {kind.value} cache epoch is gone right after it was created")

    return epoch


def pin_epochs() -> None:
    """Fix the epochs of all the cache kinds for the running job, to be done when it starts."""
    for kind in CacheKind:
        current_epoch(kind)


def rotate_epoch(kind: CacheKind) -> str | None:
    """Start a new epoch. Returns the previous one, None if there was none."""
    # With `get`, the result is the previous value, which redis-py does not reflect in the type
    previous = cast(bytes | str | None, redis_client.set(_redis_key(kind), uuid4().hex, get=True))
    return _decode(previous)


def clear_pinned_epochs() -> None:
    """Forget the epochs fixed by the running process, to be done when a new job starts."""
    for name in [n for n in os.environ if n.startswith(PINNED_EPOCH_ENV_PREFIX)]:
        del os.environ[name]
