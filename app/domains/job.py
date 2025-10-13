from enum import StrEnum, auto


class JobStatus(StrEnum):
    """Job status."""

    created = auto()
    pending = auto()
    running = auto()
    done = auto()
    error = auto()
